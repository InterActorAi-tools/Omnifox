import { useState, useEffect, useRef, lazy, Suspense } from "react";
import { useDropzone } from "react-dropzone";
import { TbFileUpload } from "react-icons/tb";
import { FaLink } from "react-icons/fa6";
import { v4 as uuidv4 } from "uuid";
// Charts load only once there are results to show.
const Graphs = lazy(() => import("./Graphs"));
import AnalysisChat from "./AnalysisChat";
import UrlQueue from "./UrlQueue";
import { useSearchParams } from "react-router-dom";
import api, { authService, endSession, errorMessage, notifyResultsChanged, RESULTS_CHANGED } from "../services/authService";

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
    const [queue, setQueue] = useState(null); // a queued list of links
    
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
                const task = await api.get(`/tasks/task_status/${taskId}`).then((res) => res.data).catch(() => null);
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
            const { data } = await api.get(`/tasks/task_status/${taskId}`, { timeout: 30000 });
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
            const { data } = await api.post(`/upload/process/${clientId}`, formData, {
                headers: { "Content-Type": "multipart/form-data" },
                timeout: 120000,
            });
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
        } catch (error) {
            if (error.response?.status === 409) return resumeRunningTask(error.response.data?.detail, "file", { selectedProject });
            console.error("Upload error:", error);
            setUploadStatus(errorMessage(error, error.response ? "Error processing file." : "Error uploading file."));
            setIsProcessing(false);
            setIsUploading(false);
            stopTokenRefreshInterval();
        }
    };

    // A task is already running (409): follow it instead of starting another.
    const resumeRunningTask = async (detail, taskType, taskMeta) => {
        const existingTaskId = typeof detail === "string" ? detail.match(/\(([^)]+)\)/)?.[1] : null;
        if (existingTaskId) return resumeTask(existingTaskId, taskType, taskMeta, 0, "Resuming existing task...");
        const active = await api.get("/tasks/me/active").then((res) => res.data.active_task).catch(() => null);
        if (active) {
            return resumeTask(active.task_id, active.task_type || taskType,
                { ...taskMeta, selectedProject: active.metadata?.project }, active.progress, active.message);
        }
        setIsProcessing(false);
        setIsUploading(false);
        stopTokenRefreshInterval();
        setUploadStatus("A task is already running. Please refresh the page to resume it.");
    };

    // Links pasted or uploaded as a list: one per line (spaces and commas also separate them).
    const links = url.split(/[\s,]+/).filter((link) => /^https?:\/\//i.test(link));
    const queueRunning = queue?.status === "processing";

    const loadQueue = () => api.get("/tasks/me/queue").then((res) => res.data.queue).catch(() => null);

    // Follow a running queue until every link is done.
    useEffect(() => {
        if (!queueRunning) return;
        const timer = setTimeout(async () => {
            const latest = (await loadQueue()) || queue;
            const done = (q) => q.items.filter((item) => item.status === "done").length;
            if (done(latest) > done(queue)) notifyResultsChanged(); // History shows the new result
            setQueue(latest);
        }, 5000);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- poll again after each update
    }, [queue]);

    const handleUrlQueue = async (urls = links) => {
        setUploadStatus("");
        try {
            const { data } = await api.post(`/process_url_queue/${clientId}`, { urls, project: selectedProject, post_context: postContext });
            setQueue({ ...data, status: "processing" });
            setUrl("");
        } catch (error) {
            setUploadStatus(errorMessage(error, "Error queuing the links."));
        }
    };

    const cancelQueue = async () => {
        await api.post(`/tasks/cancel_task/${queue.queue_id}`).catch(() => null);
        setQueue((await loadQueue()) || queue);
    };

    // A .txt, .csv or .xlsx file of links fills the links box.
    const handleLinkList = async (e) => {
        const listFile = e.target.files[0];
        e.target.value = "";
        if (!listFile) return;
        if (!/\.xlsx$/i.test(listFile.name)) {
            setUrl((await listFile.text()).split(/[\s,;]+/).filter((link) => /^https?:\/\//i.test(link)).join("\n"));
            return;
        }
        const form = new FormData();
        form.append("file", listFile);
        try {
            const { data } = await api.post("/link_list", form, { headers: { "Content-Type": "multipart/form-data" } });
            setUrl(data.links.join("\n"));
        } catch (error) {
            setUploadStatus(errorMessage(error, "Could not read the list of links."));
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
            const { data } = await api.post(`/process_url/${clientId}`, {
                url: url,
                project: selectedProject,
                post_context: postContext,
            }, { timeout: 120000 });

            if (data.success && data.completed && data.cached) {
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
            } else if (data.success && data.task_id) {
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
        } catch (error) {
            if (error.response?.status === 409) return resumeRunningTask(error.response.data?.detail, "url", { url, selectedProject });
            console.error("URL error:", error);
            setUploadStatus(errorMessage(error, error.response ? "Error processing URL." : "Error uploading URL."));
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
                    const data = await api.get(`/tasks/task_status/${taskData.taskId}`, { timeout: 15000 })
                        .then((res) => res.data).catch(() => null);
                    if (["extracting", "processing"].includes(data?.status)) {
                        resumeTask(taskData.taskId, taskData.type, taskData, data.progress, data.message);
                        return;
                    } else if (data?.status === "completed") {
                        await fetchCompletedResults(taskData.taskId);
                    }
                    localStorage.removeItem(`omnifox_active_task_${clientId}`);
                    return;
                }

                // 2. No localStorage entry — ask the server (covers cross-device and post-logout scenarios)
                const { data: serverData } = await api.get("/tasks/me/active", { timeout: 15000 });
                const active = serverData.active_task;
                if (active?.task_type === "url_queue") {
                    setQueue(await loadQueue());
                    setActiveTab("url");
                } else if (active) {
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
                const { data } = await api.get("/projects");
                setAvailableProjects(data);
                // Nothing to choose when there is only one project.
                if (data.length === 1) setSelectedProject((current) => current || data[0].name);
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
        queueRunning && "wait for the queued links to finish",
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

                    {queue && (
                        <UrlQueue
                            queue={queue}
                            onOpen={(filename) => setSearchParams({ result: filename })}
                            onCancel={cancelQueue}
                            onRetry={handleUrlQueue}
                            onDismiss={() => setQueue(null)}
                        />
                    )}

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
                                <textarea
                                    id="post-url"
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="Paste a post URL, or several (one per line)"
                                    rows={links.length > 1 ? Math.min(links.length, 10) : 1}
                                    className="border-2 border-gray-300 focus:border-[#3B9846] focus:outline-none py-1.5 pl-3 pr-12 rounded-lg w-full max-w-md transition-colors duration-300 resize-none"
                                />
                                <p className="mt-3 text-sm text-gray-600 text-center">
                                    {links.length > 1 ? `${links.length} links will be queued and analyzed one after another (up to 50). ` : ""}
                                    <label className="font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900 cursor-pointer">
                                        Upload a list of links
                                        <input type="file" accept=".txt,.csv,.xlsx" onChange={handleLinkList} className="sr-only" />
                                    </label>{" "}
                                    (.txt, .csv or .xlsx)
                                </p>
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
                            onClick={() => (activeTab === "file" ? handleUpload(file) : links.length > 1 ? handleUrlQueue() : handleUrlUpload(links[0] || url.trim()))}
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

                                        const cancelStatus = await api.post(`/tasks/cancel_task/${currentTaskId}`)
                                            .then((res) => res.status)
                                            .catch((error) => {
                                                if (!error.response) throw error;
                                                return error.response.status;
                                            });
                                        if (cancelStatus === 409) {
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