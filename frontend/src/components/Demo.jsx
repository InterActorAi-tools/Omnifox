import { useState, useEffect, useRef, lazy, Suspense } from "react";
import { useDropzone } from "react-dropzone";
import { TbFileUpload } from "react-icons/tb";
import { FaLink } from "react-icons/fa6";
import { v4 as uuidv4 } from "uuid";
// Charts load only once there are results to show.
const Graphs = lazy(() => import("./Graphs"));
import AnalysisChat from "./AnalysisChat";
import { useSearchParams } from "react-router-dom";
import { authService, endSession, notifyResultsChanged, RESULTS_CHANGED } from "../services/authService";

const Demo = ({ user }) => {
    // ✅ ALL STATE HOOKS
    const [file, setFile] = useState(null);
    const [url, setUrl] = useState("");
    const [postContext, setPostContext] = useState(""); // 🔥 NEW: Post context
    const [activeTab, setActiveTab] = useState("file");
    const [uploadStatus, setUploadStatus] = useState("");
    const [displayProgress, setDisplayProgress] = useState(0);
    const [isProcessing, setIsProcessing] = useState(false);
    const [showGraphs, setShowGraphs] = useState(false);
    const [downloadLink, setDownloadLink] = useState("");
    const [isUploading, setIsUploading] = useState(false);
    const [sentimentCounts, setSentimentCounts] = useState({ positive: 0, neutral: 0, negative: 0 });
    const [positiveContext, setPositiveContext] = useState("");
    const [neutralContext, setNeutralContext] = useState("");
    const [negativeContext, setNegativeContext] = useState("");
    const [overallSummary, setOverallSummary] = useState("");
    const [objectiveResults, setObjectiveResults] = useState([]);
    const [totalComments, setTotalComments] = useState(0);
    const [skippedComments, setSkippedComments] = useState(0);
    const [clientId, setClientId] = useState("");
    const [selectedProject, setSelectedProject] = useState("");
    const [currentTaskId, setCurrentTaskId] = useState(null);
    const [estimatedDuration, setEstimatedDuration] = useState("");
    const [availableProjects, setAvailableProjects] = useState([]);
    
    // Refs
    const progressAnimationRef = useRef(null);
    const lastProgressRef = useRef(0);
    const progressStateRef = useRef(0); // tracks real progress without stale closure
    const eventSourceRef = useRef(null);
    const tokenRefreshIntervalRef = useRef(null);
    const reconnectTimerRef = useRef(null);
    const unmountedRef = useRef(false);

    const API_URL = window.APP_CONFIG?.API_URL || "";
    // All backend routes live under /api (NPM forwards /api to the backend).
    // Build URLs with API_URL directly - the legacy BACKEND_URL split
    // produced inconsistent prefixes and is gone.

    // Proactively refresh the token before it expires during long processing runs.
    // Called every 10 minutes while a task is active.
    const startTokenRefreshInterval = () => {
        stopTokenRefreshInterval();
        tokenRefreshIntervalRef.current = setInterval(async () => {
            try {
                await authService.refreshTokens();
            } catch {
                // Refresh failed - the interceptor will handle it on the next API call
            }
        }, 10 * 60 * 1000);
    };

    const stopTokenRefreshInterval = () => {
        if (tokenRefreshIntervalRef.current) {
            clearInterval(tokenRefreshIntervalRef.current);
            tokenRefreshIntervalRef.current = null;
        }
    };

    // Wrapper around fetch that auto-refreshes on 401 before giving up.
    // H10: credentials live in HttpOnly cookies, attached automatically
    // when `credentials: "include"` is set. Mutating methods also need
    // the X-CSRF-Token header echoed from the JS-readable XSRF cookie.
    const authenticatedFetch = async (url, options = {}) => {
        const buildOpts = () => {
            const method = (options.method || "GET").toUpperCase();
            const headers = { ...(options.headers || {}) };
            if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
                const csrfMatch = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
                if (csrfMatch) {
                    headers["X-CSRF-Token"] = decodeURIComponent(csrfMatch[1]);
                }
            }
            return { ...options, credentials: "include", headers };
        };

        let response = await fetch(url, buildOpts());

        if (response.status === 401) {
            try {
                await authService.refreshTokens();
                response = await fetch(url, buildOpts());
            } catch (refreshError) {
                // Only a refused refresh ends the session (not a network error or 502).
                if (refreshError.response?.status === 401) endSession();
                return response;
            }
            if (response.status === 401) endSession();
        }

        return response;
    };

    // Use the backend's message (e.g. file too large, rate limited) when it is plain text.
    const errorDetail = async (response, fallback) => {
        const data = await response.json().catch(() => ({}));
        return typeof data.detail === "string" ? data.detail : fallback;
    };

    // Fill the results view from a finished analysis (new, cached, opened
    // from History, or updated from the chat).
    const showResult = (filename, result) => {
        setDownloadLink(`/download/${encodeURIComponent(user.email)}/${encodeURIComponent(filename)}`);
        setSentimentCounts(result.sentiment_counts || { positive: 0, neutral: 0, negative: 0 });
        setPositiveContext(result.positive_context || "");
        setNeutralContext(result.neutral_context || "");
        setNegativeContext(result.negative_context || "");
        setOverallSummary(result.overall_summary || "");
        setObjectiveResults(result.objective_results || []);
        setTotalComments(result.total_comments || 0);
        setSkippedComments(result.skipped_rows || 0);
    };

    // A result opened from History: /app?result=<filename>
    const [searchParams, setSearchParams] = useSearchParams();
    const openedResult = searchParams.get("result");
    useEffect(() => {
        if (!openedResult || !user?.email) return;
        let current = true;
        authService.getResult(openedResult)
            .then((result) => {
                if (!current) return;
                showResult(result.filename, result);
                setShowGraphs(true);
            })
            .catch(() => {
                if (!current) return;
                setShowGraphs(false);
                setUploadStatus("This result is no longer available. Results are kept for 30 days.");
            });
        return () => { current = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- load once per opened result
    }, [openedResult, user]);

    // The result on screen was deleted (from History): go back to the form.
    useEffect(() => {
        const onChange = (e) => {
            if (e.detail?.deleted && downloadLink.endsWith(`/${encodeURIComponent(e.detail.deleted)}`)) {
                resetForNewAnalysis();
            }
        };
        window.addEventListener(RESULTS_CHANGED, onChange);
        return () => window.removeEventListener(RESULTS_CHANGED, onChange);
    });

    // Back to the input form after viewing results.
    const resetForNewAnalysis = () => {
        setSearchParams({});
        setShowGraphs(false);
        setSkippedComments(0);
        setFile(null);
        setUrl("");
        setUploadStatus("");
        setDownloadLink("");
        setDisplayProgress(0);
    };

    // 🎨 SMOOTH PROGRESS ANIMATION
    const animateProgressToTarget = (targetProgress) => {
        if (progressAnimationRef.current) {
            clearInterval(progressAnimationRef.current);
        }

        const startProgress = lastProgressRef.current;
        const progressDiff = targetProgress - startProgress;
        const animationDuration = 800;
        const steps = 60;
        const stepSize = progressDiff / steps;
        const stepDuration = animationDuration / steps;

        let currentStep = 0;

        progressAnimationRef.current = setInterval(() => {
            currentStep++;
            const newProgress = startProgress + stepSize * currentStep;
            setDisplayProgress(Math.min(100, Math.max(0, newProgress)));
            if (currentStep >= steps || newProgress >= targetProgress) {
                clearInterval(progressAnimationRef.current);
                setDisplayProgress(targetProgress);
                lastProgressRef.current = targetProgress;
            }
        }, stepDuration);
    };

    const updateProgressSmooth = (newProgress, newStatus) => {
        // Compare against the ref: state would be stale inside the SSE handler.
        if (newProgress < progressStateRef.current && newProgress !== 0) return;
        progressStateRef.current = newProgress;
        setUploadStatus(newStatus);
        animateProgressToTarget(newProgress);
    };

    const getPhaseInfo = (progress) => {
        if (progress === 0) return { color: "blue", label: "Initializing..." };
        if (progress <= 5) return { color: "blue", label: "Uploading..." };
        if (progress <= 40) return { color: "orange", label: "Extracting Comments..." };
        if (progress <= 45) return { color: "yellow", label: "Preparing Analysis..." };
        if (progress <= 85) return { color: "green", label: "AI Processing..." };
        if (progress <= 95) return { color: "teal", label: "Creating Report..." };
        if (progress < 100) return { color: "purple", label: "Finalizing..." };
        return { color: "green", label: "Complete!" };
    };

    // ✅ SSE POLLING
    const pollTaskStatus = (taskId, taskType = "unknown") => {
        if (!taskId || !clientId) return;

        if (eventSourceRef.current) eventSourceRef.current.close();

        // Pin the stream to this specific task_id so reconnects don't lose context.
        // H10: the HttpOnly access_token cookie is attached automatically by
        // the browser. `withCredentials: true` is required for cross-origin
        // deploys (staging puts the API on a different subdomain); same-origin
        // sends cookies regardless.
        const progressUrl = `${API_URL}/progress/${clientId}?task_id=${encodeURIComponent(taskId)}`;

        const evtSource = new EventSource(progressUrl, { withCredentials: true });
        eventSourceRef.current = evtSource;

        evtSource.onmessage = (event) => {
            const data = event.data;
            // Server signals timeout — reconnect automatically by creating a new EventSource
            if (data === "timeout") {
                evtSource.close();
                reconnectTimerRef.current = setTimeout(() => pollTaskStatus(taskId, taskType), 500);
                return;
            }
            if (data === "-1" || data === "cancelled") {
                evtSource.close();
                stopWaiting(data === "cancelled" ? "The analysis was cancelled." : "Processing failed.");
                return;
            }

            const newProgress = parseInt(data, 10);
            if (!isNaN(newProgress) && newProgress >= 0) {
                // Use ref (not stale state) to guard against backwards jumps
                if (newProgress < progressStateRef.current) return;

                let message = "Processing...";
                if (newProgress < 5) message = "Initializing...";
                else if (newProgress <= 40) message = "Extracting Comments...";
                else if (newProgress <= 85) message = "AI Processing...";
                else if (newProgress < 100) message = "Finalizing...";

                updateProgressSmooth(newProgress, message);

                if (newProgress === 100) {
                    updateProgressSmooth(100, "Completed! Loading results...");
                    evtSource.close();
                    setTimeout(() => fetchCompletedResults(taskId), 500);
                }
            }
        };

        evtSource.onerror = () => {
            // The browser retries dropped connections by itself, but gives up
            // (CLOSED) on an error response such as 401 after the access token
            // expired (e.g. the laptop slept). Renew the session, then follow
            // the task again - or show its result if it finished meanwhile.
            if (evtSource.readyState !== EventSource.CLOSED) return;
            reconnectTimerRef.current = setTimeout(async () => {
                try {
                    await authService.refreshTokens();
                } catch (refreshError) {
                    if (refreshError.response?.status === 401) return endSession();
                }
                if (unmountedRef.current || eventSourceRef.current !== evtSource) return;
                const response = await authenticatedFetch(`${API_URL}/tasks/task_status/${taskId}`).catch(() => null);
                const task = response?.ok ? await response.json() : null;
                if (task?.status === "completed") fetchCompletedResults(taskId);
                else if (task && ["extracting", "processing"].includes(task.status)) pollTaskStatus(taskId, taskType);
                else stopWaiting(task?.status === "cancelled" ? "The analysis was cancelled." : "Lost track of the analysis. Check History for the result.");
            }, 2000);
        };
    };

    // Stop showing progress for the current task and say why.
    const stopWaiting = (message) => {
        setUploadStatus(message);
        setIsProcessing(false);
        setIsUploading(false);
        stopTokenRefreshInterval();
        localStorage.removeItem(`omnifox_active_task_${clientId}`);
    };

    const fetchCompletedResults = async (taskId) => {
        try {
            const response = await authenticatedFetch(`${API_URL}/tasks/task_status/${taskId}`, {
                signal: AbortSignal.timeout(30000),
            });

            if (response.ok) {
                const data = await response.json();
                if (data.status === "completed" && data.data) {
                    const resultData = data.data;
                    setSearchParams({});
                    showResult(resultData.new_filename, resultData);

                    setTimeout(() => {
                        setShowGraphs(true);
                        setIsProcessing(false);
                        setIsUploading(false);
                    }, 1000);

                    localStorage.removeItem(`omnifox_active_task_${clientId}`);

                    notifyResultsChanged();
                    return;
                }
            }
            stopWaiting("Completed, but the results could not be loaded. Check History for the result.");
        } catch (error) {
            console.error("Error fetching results:", error);
            stopWaiting("Completed, but the results could not be loaded. Check History for the result.");
        } finally {
            stopTokenRefreshInterval();
        }
    };

    const handleUpload = async (file) => {
        if (!file || !clientId || !selectedProject) {
            setUploadStatus("Please select a file and project.");
            return;
        }

        // Block a second simultaneous process
        if (isProcessing) {
            setUploadStatus("A processing task is already running. Please wait for it to finish.");
            return;
        }

        setDisplayProgress(0);
        lastProgressRef.current = 0;
        progressStateRef.current = 0;
        setIsProcessing(true);
        setIsUploading(true);
        updateProgressSmooth(2, "Uploading file...");
        startTokenRefreshInterval();

        const formData = new FormData();
        formData.append("file", file);
        formData.append("project", selectedProject);
        if (postContext) formData.append("post_context", postContext);

        try {
            const response = await authenticatedFetch(`${API_URL}/upload/process/${clientId}`, {
                method: "POST",
                body: formData,
                signal: AbortSignal.timeout(120000),
            });

            if (response.status === 409) {
                // Another task is already running — resume it instead of erroring
                const errData = await response.json().catch(() => ({}));
                const existingTaskId = errData.detail?.match(/\(([^)]+)\)/)?.[1];
                if (existingTaskId) {
                    resumeTask(existingTaskId, "file", { selectedProject }, 0, "Resuming existing task...");
                } else {
                    // Task ID not in response body — ask the server which task is active
                    try {
                        const activeResp = await authenticatedFetch(`${API_URL}/tasks/me/active`);
                        if (activeResp.ok) {
                            const activeData = await activeResp.json();
                            const active = activeData.active_task;
                            if (active) {
                                resumeTask(active.task_id, active.task_type || "file",
                                    { selectedProject: active.metadata?.project }, active.progress, active.message);
                                return;
                            }
                        }
                    } catch { /* fall through to reset */ }
                    // Could not locate the running task — reset UI cleanly
                    setIsProcessing(false);
                    setIsUploading(false);
                    stopTokenRefreshInterval();
                    setUploadStatus("A task is already running. Please refresh the page to resume it.");
                }
                return;
            } else if (response.ok) {
                const data = await response.json();
                if (data.success && data.task_id) {
                    setCurrentTaskId(data.task_id);
                    updateProgressSmooth(5, "File uploaded, starting processing...");
                    localStorage.setItem(
                        `omnifox_active_task_${clientId}`,
                        JSON.stringify({
                            taskId: data.task_id,
                            type: "file",
                            fileName: file.name,
                            selectedProject,
                        })
                    );
                    setTimeout(() => pollTaskStatus(data.task_id, "file"), 1000);
                } else {
                    stopWaiting(data.message || "Error processing file.");
                }
            } else {
                setUploadStatus(await errorDetail(response, "Error processing file."));
                setIsProcessing(false);
                setIsUploading(false);
                stopTokenRefreshInterval();
            }
        } catch (error) {
            console.error("Upload error:", error);
            setUploadStatus("Error uploading file.");
            setIsProcessing(false);
            setIsUploading(false);
            stopTokenRefreshInterval();
        }
    };

    const handleUrlUpload = async (url) => {
        if (!clientId || !url.trim() || !selectedProject) {
            setUploadStatus("Please check URL and Project selection.");
            return;
        }

        // Block a second simultaneous process
        if (isProcessing) {
            setUploadStatus("A processing task is already running. Please wait for it to finish.");
            return;
        }

        setDisplayProgress(0);
        lastProgressRef.current = 0;
        progressStateRef.current = 0;
        setIsProcessing(true);
        setIsUploading(true);
        updateProgressSmooth(2, "Connecting to extraction service...");
        startTokenRefreshInterval();

        try {
            const response = await authenticatedFetch(`${API_URL}/process_url/${clientId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    url: url,
                    project: selectedProject,
                    post_context: postContext,
                }),
                signal: AbortSignal.timeout(120000),
            });

            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    if (data.completed && data.cached) {
                        updateProgressSmooth(100, "Cached results loaded!");
                        stopTokenRefreshInterval();
                        setTimeout(() => {
                            setIsProcessing(false);
                            setIsUploading(false);
                            if (data.new_filename) {
                                setSearchParams({});
                                showResult(data.new_filename, { ...data, total_comments: data.comments_count || data.total_comments });
                                setShowGraphs(true);
                                notifyResultsChanged();
                            } else {
                                stopWaiting("The saved result is no longer available. Please run the analysis again.");
                            }
                        }, 1000);
                    } else if (data.task_id) {
                        setCurrentTaskId(data.task_id);
                        updateProgressSmooth(5, data.message || "Starting extraction...");
                        localStorage.setItem(
                            `omnifox_active_task_${clientId}`,
                            JSON.stringify({
                                taskId: data.task_id,
                                type: "url",
                                url,
                                selectedProject,
                            })
                        );
                        setTimeout(() => pollTaskStatus(data.task_id, "url"), 1000);
                    } else {
                        stopWaiting(data.message || "Error processing URL.");
                    }
                } else {
                    stopWaiting(data.message || "Error processing URL.");
                }
            } else if (response.status === 409) {
                const errData = await response.json().catch(() => ({}));
                const existingTaskId = errData.detail?.match(/\(([^)]+)\)/)?.[1];
                if (existingTaskId) {
                    resumeTask(existingTaskId, "url", { url, selectedProject }, 0, "Resuming existing task...");
                } else {
                    try {
                        const activeResp = await authenticatedFetch(`${API_URL}/tasks/me/active`);
                        if (activeResp.ok) {
                            const activeData = await activeResp.json();
                            const active = activeData.active_task;
                            if (active) {
                                resumeTask(active.task_id, active.task_type || "url",
                                    { url, selectedProject: active.metadata?.project }, active.progress, active.message);
                                return;
                            }
                        }
                    } catch { /* fall through to reset */ }
                    setIsProcessing(false);
                    setIsUploading(false);
                    stopTokenRefreshInterval();
                    setUploadStatus("A task is already running. Please refresh the page to resume it.");
                }
                return;
            } else {
                setUploadStatus(await errorDetail(response, "Error processing URL."));
                setIsProcessing(false);
                setIsUploading(false);
                stopTokenRefreshInterval();
            }
        } catch (error) {
            console.error("URL error:", error);
            setUploadStatus("Error uploading URL.");
            setIsProcessing(false);
            setIsUploading(false);
            stopTokenRefreshInterval();
        }
    };

    // ✅ CLIENT ID SETUP
    useEffect(() => {
        if (user?.email) {
            setClientId(user.email);
            localStorage.setItem("omnifox_client_id", user.email);
        } else {
            const storedClientId = localStorage.getItem("omnifox_client_id");
            if (storedClientId) {
                setClientId(storedClientId);
            } else {
                const newClientId = uuidv4();
                localStorage.setItem("omnifox_client_id", newClientId);
                setClientId(newClientId);
            }
        }
    }, [user]);

    // Resume a task given its ID and optional cached metadata
    const resumeTask = (taskId, taskType, taskMeta, serverProgress, serverMessage) => {
        setCurrentTaskId(taskId);
        setIsProcessing(true);
        setIsUploading(true);
        startTokenRefreshInterval();

        const currentProgress = serverProgress || 0;
        setDisplayProgress(currentProgress);
        lastProgressRef.current = currentProgress;
        progressStateRef.current = currentProgress;
        setUploadStatus(serverMessage || "Resuming...");

        if (taskMeta?.estimatedDuration) setEstimatedDuration(taskMeta.estimatedDuration);
        if (taskMeta?.selectedProject) setSelectedProject(taskMeta.selectedProject);
        if (taskType === "url" && taskMeta?.url) {
            setUrl(taskMeta.url);
            setActiveTab("url");
        } else if (taskType === "file") {
            setActiveTab("file");
        }

        pollTaskStatus(taskId, taskType || "file");
    };

    // ✅ RESUME TASKS ON LOAD — checks localStorage first, then server
    useEffect(() => {
        const checkForResumableTasks = async () => {
            if (!clientId) return;

            try {
                // 1. Check localStorage (survives refresh/close; preserved across logout since Issue 1 fix)
                const stored = localStorage.getItem(`omnifox_active_task_${clientId}`);
                if (stored) {
                    const taskData = JSON.parse(stored);
                    const response = await authenticatedFetch(
                        `${API_URL}/tasks/task_status/${taskData.taskId}`,
                        { signal: AbortSignal.timeout(15000) }
                    );

                    if (response.ok) {
                        const data = await response.json();
                        if (["extracting", "processing"].includes(data.status)) {
                            resumeTask(taskData.taskId, taskData.type, taskData, data.progress, data.message);
                            return;
                        } else if (data.status === "completed") {
                            await fetchCompletedResults(taskData.taskId);
                        }
                    }
                    localStorage.removeItem(`omnifox_active_task_${clientId}`);
                    return;
                }

                // 2. No localStorage entry — ask the server (covers cross-device and post-logout scenarios)
                const serverResponse = await authenticatedFetch(
                    `${API_URL}/tasks/me/active`,
                    { signal: AbortSignal.timeout(15000) }
                );

                if (serverResponse.ok) {
                    const serverData = await serverResponse.json();
                    const active = serverData.active_task;
                    if (active) {
                        // Persist so future refreshes use the fast path
                        localStorage.setItem(
                            `omnifox_active_task_${clientId}`,
                            JSON.stringify({
                                taskId: active.task_id,
                                type: active.task_type || "file",
                                selectedProject: active.metadata?.project || "",
                            })
                        );
                        resumeTask(
                            active.task_id,
                            active.task_type || "file",
                            { selectedProject: active.metadata?.project },
                            active.progress,
                            active.message
                        );
                    }
                }
            } catch (error) {
                console.error("Error checking resumable tasks:", error);
                localStorage.removeItem(`omnifox_active_task_${clientId}`);
            }
        };

        if (clientId) {
            checkForResumableTasks();
        }
    }, [clientId]);

    // ✅ NEW: Fetch projects from the backend
    useEffect(() => {
        const fetchProjects = async () => {
            try {
                const response = await authenticatedFetch(`${API_URL}/projects`);
                if (response.ok) {
                    const data = await response.json();
                    setAvailableProjects(data);
                    // Nothing to choose when there is only one project.
                    if (data.length === 1) setSelectedProject((current) => current || data[0].name);
                }
            } catch (error) {
                console.error("Failed to load projects", error);
            }
        };

        fetchProjects();
    }, []);

    // ✅ CLEANUP
    useEffect(() => {
        return () => {
            if (progressAnimationRef.current) clearInterval(progressAnimationRef.current);
            if (eventSourceRef.current) eventSourceRef.current.close();
            clearTimeout(reconnectTimerRef.current);
            unmountedRef.current = true;
            stopTokenRefreshInterval();
        };
    }, []);

    const { getRootProps, getInputProps } = useDropzone({
        onDrop: (acceptedFiles) => {
            if (acceptedFiles[0]) {
                setFile(acceptedFiles[0]);
                setUploadStatus("");
            }
        },
        onDropRejected: () => setUploadStatus("Only Excel .xlsx files are supported."),
        multiple: false,
        accept: { "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [] },
    });

    if (showGraphs) {
        return (
            <Suspense fallback={<p role="status" className="mt-5 text-gray-600">Loading results…</p>}>
                <Graphs
                    downloadLink={downloadLink}
                    sentimentCounts={sentimentCounts}
                    positiveContext={positiveContext}
                    neutralContext={neutralContext}
                    negativeContext={negativeContext}
                    overallSummary={overallSummary}
                    objectiveResults={objectiveResults}
                    totalComments={totalComments}
                    skippedComments={skippedComments}
                    onReset={resetForNewAnalysis}
                />
                {downloadLink && (
                    <AnalysisChat
                        key={downloadLink}
                        filename={decodeURIComponent(downloadLink.split("/").pop())}
                        onUpdate={(result) => showResult(result.filename, result)}
                    />
                )}
            </Suspense>
        );
    }

    const phaseInfo = getPhaseInfo(displayProgress);

    const missingInput = [
        activeTab === "file" && !file && "choose an Excel file",
        activeTab === "url" && url.trim() === "" && "paste a post URL",
        selectedProject === "" && "pick a project",
    ].filter(Boolean);
    const missingInputText = missingInput.length ? `To analyze, ${missingInput.join(" and ")}.` : "";

    // ✅ MAIN COMPONENT JSX
    return (
        <div className="flex flex-col justify-center items-center w-full max-w-4xl p-4 sm:p-8 rounded-2xl shadow-lg bg-white mt-5 space-y-6 sm:space-y-8">
            {!isUploading ? (
                <>
                    {/* Header */}

                    {/* Toggle Button */}
                    <div className="flex bg-gray-100 rounded-full p-1 w-fit mx-auto mb-6">
                        <button
                            onClick={() => setActiveTab("file")}
                            aria-pressed={activeTab === "file"}
                            className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all duration-300 ${
                                activeTab === "file" ? "bg-[#2E7D38] text-white shadow-sm" : "text-gray-600 hover:text-gray-800"
                            }`}>
                            <TbFileUpload size={16} aria-hidden="true" />
                            Upload file
                        </button>
                        <button
                            onClick={() => setActiveTab("url")}
                            aria-pressed={activeTab === "url"}
                            className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all duration-300 ${
                                activeTab === "url" ? "bg-[#2E7D38] text-white shadow-sm" : "text-gray-600 hover:text-gray-800"
                            }`}>
                            <FaLink size={16} aria-hidden="true" />
                            Extract from URL
                        </button>
                    </div>

                    {/* Content Area */}
                    <div className="w-full">
                        {activeTab === "file" ? (
                            <div
                                {...getRootProps({ role: "button", "aria-label": file ? `Selected file: ${file.name}. Press Enter to choose a different file.` : "Upload an Excel file: press Enter to choose a file, or drag and drop it here." })}
                                className="w-full flex flex-col items-center justify-center cursor-pointer border-2 border-dashed border-gray-300 p-6 sm:p-8 rounded-lg hover:border-[#3B9846] transition-colors duration-300">
                                <input {...getInputProps()} className="hidden" />
                                <TbFileUpload size={48} aria-hidden="true" className="text-gray-500 mb-4" />
                                <p className="text-black font-semibold text-lg mb-2">
                                    Drag & Drop or <span className="text-[#2E7D38] hover:text-green-600">choose file</span> to upload
                                </p>
                                <p className="text-sm text-gray-600">Excel (.xlsx) files with a &quot;Text&quot; column</p>
                                {file && (
                                    <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
                                        <p className="font-medium text-green-800">Selected: <bdi>{file.name}</bdi></p>
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="w-full flex flex-col items-center justify-center border-2 border-dashed border-gray-300 p-6 sm:p-8 rounded-lg">
                                <FaLink size={48} aria-hidden="true" className="text-gray-500 mb-4" />
                                <label htmlFor="post-url" className="text-black font-semibold text-lg mb-6">Export comments from URL</label>
                                <input
                                    id="post-url"
                                    type="url"
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="Enter a URL (Facebook, Instagram, YouTube, etc.)"
                                    className="border-2 border-gray-300 focus:border-[#3B9846] focus:outline-none py-1.5 pl-3 pr-12 rounded-lg w-full max-w-md transition-colors duration-300"
                                />
                            </div>
                        )}
                        {activeTab === "file" && (
                            <p className="mt-3 text-sm text-gray-600 text-center">
                                Not sure about the format?{" "}
                                <a href="/sample_input.xlsx" download className="font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900">
                                    Download an example sheet
                                </a>
                            </p>
                        )}
                    </div>

                    {/* 🔥 NEW: Post Context Input */}
                    <div className="w-full max-w-2xl mx-auto">
                        <label htmlFor="post-context" className="block text-sm font-medium text-gray-700 mb-2">
                            <span aria-hidden="true">📝 </span>Post Context (Optional)
                            <span className="text-gray-600 ml-2 font-normal">Helps AI understand the topic better</span>
                        </label>
                        <textarea
                            id="post-context"
                            dir="auto"
                            maxLength={2048}
                            value={postContext}
                            onChange={(e) => setPostContext(e.target.value)}
                            placeholder="Enter the original post text here for better analysis context..."
                            className="border-2 border-gray-300 focus:border-[#3B9846] focus:outline-none py-2 px-3 rounded-lg w-full transition-colors duration-300 resize-none"
                            rows={3}
                        />
                    </div>

                    {uploadStatus && (
                        <p role="status" className="w-full max-w-2xl mx-auto text-center text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
                            {uploadStatus}
                        </p>
                    )}

                    {/* Project Selection and Analyze Button */}
                    <div className="flex flex-col sm:flex-row sm:items-center sm:space-x-4 space-y-4 sm:space-y-0 w-full max-w-md mx-auto">
                    <select
                            aria-label="Project"
                            className="border border-gray-300 rounded-lg py-1.5 pl-3 pr-12 focus:outline-none focus:ring-2 focus:ring-[#3B9846] flex-1 text-gray-600 text-left"
                            value={selectedProject}
                            onChange={(e) => setSelectedProject(e.target.value)}
                            required>
                            <option value="" disabled>
                                Select project*
                            </option>
                            
                            {/* ✅ DYNAMIC LIST: Maps through the projects from DB */}
                            {availableProjects.length > 0 ? (
                                availableProjects.map((project) => (
                                    <option key={project.id || project.name} value={project.name}>
                                        {project.name}
                                    </option>
                                ))
                            ) : (
                                <option disabled>No projects found (Ask Admin)</option>
                            )}
                        </select>
                        
                        <button
                            onClick={() => (activeTab === "file" ? handleUpload(file) : handleUrlUpload(url))}
                            disabled={!!missingInputText}
                            aria-describedby="analyze-hint"
                            className={`font-semibold py-1.5 px-12 rounded-lg flex items-center justify-center gap-2 min-w-[120px] transition-all duration-300 ${
                                missingInputText
                                    ? "bg-gray-300 cursor-not-allowed text-gray-600"
                                    : "bg-[#2E7D38] hover:bg-[#256A2E] text-white shadow-md hover:shadow-lg"
                            }`}>
                            Analyze
                        </button>
                    </div>
                    {/* Says why Analyze is disabled instead of leaving a dead button. */}
                    <p id="analyze-hint" aria-live="polite" className="text-sm text-gray-600 text-center -mt-2 min-h-[1.25rem]">
                        {missingInputText}
                    </p>
                </>
            ) : (
                <div className="w-full text-center">
                    {/* Progress Bar */}
                    <div
                        role="progressbar"
                        aria-label="Analysis progress"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={Math.round(displayProgress)}
                        className="w-full bg-gray-200 rounded-full h-4 mb-4 overflow-hidden shadow-inner">
                        <div
                            className={`h-full rounded-full transition-all duration-300 ease-out bg-gradient-to-r ${
                                phaseInfo.color === "blue"
                                    ? "from-blue-400 to-blue-600"
                                    : phaseInfo.color === "orange"
                                    ? "from-orange-400 to-orange-600"
                                    : phaseInfo.color === "yellow"
                                    ? "from-yellow-400 to-yellow-600"
                                    : phaseInfo.color === "green"
                                    ? "from-green-400 to-green-600"
                                    : phaseInfo.color === "teal"
                                    ? "from-teal-400 to-teal-600"
                                    : phaseInfo.color === "purple"
                                    ? "from-purple-400 to-purple-600"
                                    : "from-green-400 to-green-600"
                            }`}
                            style={{
                                width: `${displayProgress}%`,
                                boxShadow: displayProgress > 0 ? "inset 0 1px 2px rgba(255,255,255,0.3)" : "none",
                            }}>
                            {displayProgress > 15 && (
                                <div className="h-full flex items-center justify-end pr-2">
                                    <span className="text-white text-xs font-semibold">{Math.round(displayProgress)}%</span>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Status Display */}
                    <div className="mt-4 space-y-2" aria-live="polite">
                        <div className="flex items-center justify-center gap-2">
                            <div
                                className={`w-2 h-2 rounded-full animate-pulse ${
                                    phaseInfo.color === "blue"
                                        ? "bg-blue-500"
                                        : phaseInfo.color === "orange"
                                        ? "bg-orange-500"
                                        : phaseInfo.color === "yellow"
                                        ? "bg-yellow-500"
                                        : phaseInfo.color === "green"
                                        ? "bg-green-500"
                                        : phaseInfo.color === "teal"
                                        ? "bg-teal-500"
                                        : phaseInfo.color === "purple"
                                        ? "bg-purple-500"
                                        : "bg-green-500"
                                }`}
                            />
                            <p className="text-lg font-semibold text-gray-800">{phaseInfo.label}</p>
                        </div>

                        <p className="text-sm text-gray-600">{uploadStatus}</p>

                        {estimatedDuration && displayProgress < 95 && <p className="text-xs text-gray-500">Estimated time: {estimatedDuration}</p>}
                    </div>

                    {/* Cancel Button */}
                    {currentTaskId && isProcessing && (
                        <div className="mt-6 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg">
                            <p className="text-xs text-blue-800 mb-2">💡 You can safely refresh the page - your progress will be restored automatically</p>
                            <button
                                onClick={async () => {
                                    try {
                                        if (eventSourceRef.current) {
                                            eventSourceRef.current.close();
                                            eventSourceRef.current = null;
                                        }
                                        stopTokenRefreshInterval();

                                        const cancelResponse = await authenticatedFetch(`${API_URL}/tasks/cancel_task/${currentTaskId}`, {
                                            method: "POST",
                                        });
                                        if (cancelResponse.status === 409) {
                                            // It finished just before the click: show the result instead.
                                            fetchCompletedResults(currentTaskId);
                                            return;
                                        }

                                        setIsProcessing(false);
                                        setIsUploading(false);
                                        setUploadStatus("Task cancelled by user");
                                        setCurrentTaskId(null);
                                        setDisplayProgress(0);
                                        progressStateRef.current = 0;
                                        localStorage.removeItem(`omnifox_active_task_${clientId}`);
                                    } catch (error) {
                                        console.error("Error cancelling task:", error);
                                    }
                                }}
                                className="mt-5 bg-red-600 text-white font-semibold py-1.5 px-12 rounded-lg hover:bg-red-700 text-sm transition-colors duration-200">
                                Cancel Processing
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default Demo;