import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { authService, errorMessage } from '../services/authService';
import api from "../services/authService";
import {
    AiOutlineArrowLeft,
    AiOutlineLogout,
    AiOutlineDesktop,
    AiOutlineHistory,
    AiOutlineUser,
    AiOutlineDelete,
    AiOutlineEdit,
    AiOutlineAreaChart,
    AiOutlinePlus,
    AiOutlineFolder,
    AiOutlineLock,
    AiOutlineShareAlt,
    AiOutlineLineChart,
    AiOutlineKey,
} from "react-icons/ai";
import EnhancedDashboard from "./EnhancedDashboard";
import Modal from "./Modal";
import ProjectTrends from "./ProjectTrends";
import { wordmark } from "../assets";
import { clearAuthStorage } from "../services/authService";

// Reusable "Card" component for consistent look
const DashboardCard = ({ children, className = "" }) => <div className={`bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden ${className}`}>{children}</div>;

// Reusable Section Header
const TabHeader = ({ title, subtitle, action }) => (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
            <h2 className="text-xl font-bold text-gray-800">{title}</h2>
            {subtitle && <p className="text-sm text-gray-600 mt-1">{subtitle}</p>}
        </div>
        {action && <div>{action}</div>}
    </div>
);



// --- 1. Message Modal (For Success/Error) ---
const MessageModal = ({ message, type, onClose }) => {
    if (!message) return null;
    const isError = type === "error";
    return (
        <Modal title={isError ? "Error" : "Success"} onClose={onClose} className="max-w-sm text-center flex flex-col" titleClassName="text-xl font-bold text-gray-900 mb-2">
            <div aria-hidden="true" className={`mx-auto flex items-center justify-center h-14 w-14 rounded-full mb-4 -order-1 ${
                isError ? "bg-red-50 text-red-600" : "bg-green-50 text-green-700"
            }`}>
                {isError ? (
                    <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                ) : (
                    <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
                    </svg>
                )}
            </div>
            <p role={isError ? "alert" : "status"} className="text-sm text-gray-600 mb-6">{message}</p>
            <button onClick={onClose} className={`w-full py-3 rounded-xl text-white font-semibold transition-all ${
                isError ? "bg-red-600 hover:bg-red-700" : "bg-[#2E7D38] hover:bg-[#256A2E]"
            }`}>
                Okay, got it
            </button>
        </Modal>
    );
};

// --- 2. Confirmation Modal (For Deleting) ---
const ConfirmModal = ({ isOpen, title, message, onConfirm, onCancel, isDeleting }) => {
    if (!isOpen) return null;
    return (
        <Modal title={title} onClose={onCancel} className="max-w-sm text-center" titleClassName="text-xl font-bold text-gray-900 mb-2">
            <p className="text-sm text-gray-600 mb-6">{message}</p>
            <div className="flex space-x-3">
                <button onClick={onCancel} className="flex-1 py-3 bg-gray-100 text-gray-700 rounded-xl font-semibold hover:bg-gray-200 transition-all">
                    Cancel
                </button>
                <button onClick={onConfirm} disabled={isDeleting} className="flex-1 py-3 bg-red-600 text-white rounded-xl font-semibold hover:bg-red-700 transition-all">
                    {isDeleting ? "Deleting..." : "Yes, Delete"}
                </button>
            </div>
        </Modal>
    );
};

export default function Dashboard() {
    const navigate = useNavigate();
    const [user, setUser] = useState(authService.getStoredUser());
    const [users, setUsers] = useState([]);
    const [joinRequests, setJoinRequests] = useState([]);
    const [joinRoles, setJoinRoles] = useState({});
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState("analytics");

    // Invite System State
    const [showAddUser, setShowAddUser] = useState(false);
    const [newUser, setNewUser] = useState({ email: "", name: "" });
    const [generatedLink, setGeneratedLink] = useState("");
    const [showCreateUser, setShowCreateUser] = useState(false);
    const [createForm, setCreateForm] = useState({ email: "", name: "", password: "", role: "basic_user" });

    // Edit/Reset State
    const [editingUser, setEditingUser] = useState(null);
    const [resetLink, setResetLink] = useState(null);
    const [selectedRoles, setSelectedRoles] = useState([]);
    const [roles, setRoles] = useState([]);

    // Session View State
    const [viewingSessionsUser, setViewingSessionsUser] = useState(null);
    const [userSessions, setUserSessions] = useState([]);
    const [sessionsError, setSessionsError] = useState("");

    const isAdmin = user?.permissions?.includes("manage_users");
    const canViewAnalytics = user?.permissions?.includes("view_dashboard");
    const canCreatePrivate = user?.permissions?.includes("create_private_projects");
    const canManageProjects = isAdmin || canCreatePrivate;

    //Project state 
    const [projects, setProjects] = useState([]);
    const [showAddProject, setShowAddProject] = useState(false);
    const [newProjectName, setNewProjectName] = useState("");
    const [newProjectObjectives, setNewProjectObjectives] = useState("");
    const [newProjectPrivate, setNewProjectPrivate] = useState(false);
    const [sharingProject, setSharingProject] = useState(null);
    const [keyStatus, setKeyStatus] = useState(null);
    const [recovery, setRecovery] = useState({ code: "", password: "" });
    const [trendsProject, setTrendsProject] = useState(null);
    const [shareEmails, setShareEmails] = useState("");
    const [editingProject, setEditingProject] = useState(null);
    const [editObjectives, setEditObjectives] = useState("");
    const [modalConfig, setModalConfig] = useState(null); 
    const [confirmConfig, setConfirmConfig] = useState({ 
        isOpen: false, 
        id: null, 
        type: null // 'project' or 'user'
    });
    const showModal = (message, type = "success") => {
        setModalConfig({ message, type });
    };

    useEffect(() => {
        loadDashboardData();
    }, []);

    const loadDashboardData = async () => {
        try {
            const userData = await authService.getCurrentUser();
            setUser(userData);

            if (userData.permissions?.includes("manage_users")) {
                loadAdminData();
            }
            if (userData.permissions?.includes("manage_users") || userData.permissions?.includes("create_private_projects")) {
                loadProjects();
            }
        } catch (error) {
            console.error("Failed to load dashboard:", error);
        } finally {
            setLoading(false);
        }
    };

    const loadAdminData = async () => {
        try {
            const [usersData, rolesData, requestsData] = await Promise.all([
                api.get("/admin/users").then((res) => res.data),
                api.get("/admin/roles").then((res) => res.data),
                api.get("/admin/join-requests").then((res) => res.data),
            ]);
            setUsers(usersData);
            setRoles(rolesData);
            setJoinRequests(requestsData);
        } catch (error) {
            console.error("Failed to load admin data:", error);
        }
    };

    const loadProjects = async () => {
        setProjects(await api.get("/projects").then((res) => res.data).catch(() => []));
        setKeyStatus(await authService.getMyKeys().catch(() => null));
    };

    const handleRecoverKey = async (e) => {
        e.preventDefault();
        try {
            await authService.recoverKey(recovery.code, recovery.password);
            setRecovery({ code: "", password: "" });
            loadProjects();
            showModal("Your private projects are unlocked", "success");
        } catch (error) {
            showModal(errorMessage(error, "Could not unlock your private projects"), "error");
        }
    };

    const handleResetKey = async () => {
        if (!recovery.password) {
            showModal("Enter your password first", "error");
            return;
        }
        if (!window.confirm("Start over with a new key? Private projects that only you can open will be deleted, and owners will need to share theirs with you again.")) return;
        try {
            await authService.resetKey(recovery.password);
            setRecovery({ code: "", password: "" });
            loadProjects();
        } catch (error) {
            showModal(errorMessage(error, "Could not reset your key"), "error");
        }
    };

    // --- HANDLERS (Identical Logic, kept compact) ---
    const handleInviteUser = async (e) => {
        e.preventDefault();
        try {
            const response = await api.post("/admin/invitations/generate", { 
                email: newUser.email, 
                name: newUser.name, 
                role: "basic_user" 
            });
            setGeneratedLink(response.data.link);
            loadAdminData();
            // 👇 Uses the fancy modal instead of alert()
            showModal("Invitation link generated!", "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to generate invite"), "error");
        }
    };

    const handleCreateUser = async (e) => {
        e.preventDefault();
        try {
            await api.post("/admin/users", createForm);
            setCreateForm({ email: "", name: "", password: "", role: "basic_user" });
            setShowCreateUser(false);
            loadAdminData();
            showModal("Account created. Send them the email and temporary password; they choose their own at first sign-in.", "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to create the account"), "error");
        }
    };

    const handleJoinRequest = async (r, accept) => {
        try {
            if (accept) {
                await api.post(`/admin/join-requests/${r.id}/accept`, { role: joinRoles[r.id] || "basic_user" });
            } else {
                await api.delete(`/admin/join-requests/${r.id}`);
            }
            loadAdminData();
            showModal(accept ? `${r.email} can now log in` : "Request rejected", "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to update the request"), "error");
        }
    };

    const handleUpdateRoles = async () => {
        try {
            await api.put(`/admin/users/${editingUser.id}/roles`, { role_names: selectedRoles });
            setEditingUser(null);
            setSelectedRoles([]);
            loadAdminData();
            showModal("Roles updated successfully", "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to update roles"), "error");
        }
    };

    const handleLogout = async () => {
        try {
            await authService.logout();
        } finally {
            clearAuthStorage();
            window.location.href = "/login";
        }
    };

    const closeEditRoles = () => {
        setEditingUser(null);
        setSelectedRoles([]);
    };

    const handleViewSessions = async (targetUser) => {
        setViewingSessionsUser(targetUser);
        setUserSessions([]);
        setSessionsError("");
        try {
            setUserSessions(await authService.getAdminUserSessions(targetUser.id));
        } catch {
            setSessionsError("Could not load this user's sessions. Please try again.");
        }
    };

    const handleAdminRevokeSession = async (sessionId) => {
        setSessionsError("");
        try {
            await authService.adminRevokeSession(viewingSessionsUser.id, sessionId);
            setUserSessions(await authService.getAdminUserSessions(viewingSessionsUser.id));
        } catch {
            setSessionsError("Could not sign out that session. Please try again.");
        }
    };

    // Project Handlers
    const handleAddProject = async (e) => {
        e.preventDefault();
        try {
            // Only admins create shared projects; everyone else's are private.
            const isPrivate = isAdmin ? newProjectPrivate : true;
            await api.post("/projects", { name: newProjectName, objectives: newProjectObjectives.split("\n"), is_private: isPrivate });
            setNewProjectName("");
            setNewProjectObjectives("");
            setNewProjectPrivate(false);
            setShowAddProject(false);
            loadProjects();
            // 👇 Uses the fancy modal instead of alert()
            showModal("Project added successfully", "success"); 
        } catch (error) {
            showModal(errorMessage(error, "Failed to add project"), "error");
        }
    };

    const openShareProject = (project) => {
        setSharingProject(project);
        setShareEmails(project.shared_with.join("\n"));
    };

    const handleShareProject = async (e) => {
        e.preventDefault();
        try {
            const emails = shareEmails.split(/[\s,]+/).filter(Boolean);
            await api.put(`/projects/${sharingProject.id}/shares`, { emails });
            setSharingProject(null);
            loadProjects();
            showModal("Sharing updated", "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to update sharing"), "error");
        }
    };

    const openEditObjectives = (project) => {
        setEditingProject(project);
        setEditObjectives(project.objectives.join("\n"));
    };

    const handleEditObjectives = async (e) => {
        e.preventDefault();
        try {
            await api.put(`/projects/${editingProject.id}/objectives`, { objectives: editObjectives.split("\n") });
            setEditingProject(null);
            loadProjects();
            showModal("Objectives updated. New uploads are scored against them.", "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to update objectives"), "error");
        }
    };

    const handleResetLink = async (u) => {
        try {
            const { data } = await api.post(`/admin/users/${u.id}/reset-link`);
            setResetLink({ email: u.email, link: data.link });
        } catch (error) {
            showModal(errorMessage(error, "Failed to create a reset link"), "error");
        }
    };

    // 1. Trigger the Modal (User clicks Trash Icon)
    const confirmDeleteProject = (id) => {
        setConfirmConfig({ isOpen: true, id: id, type: 'project' });
    };

    const confirmDeleteUser = (id) => {
        setConfirmConfig({ isOpen: true, id: id, type: 'user' });
    };

// 2. Actually Delete (User clicks "Yes" in Modal)
    const executeDelete = async () => {
        const { id, type } = confirmConfig;
        if (!id) return;
        setConfirmConfig({ isOpen: false, id: null, type: null });

        try {
            // ✅ FIX 1: Use relative paths (remove BACKEND_URL)
            let url = type === 'project' 
                ? `/projects/${id}` 
                : `/admin/users/${id}`;

            await api.delete(url);

            if (type === 'project') loadProjects(); else loadAdminData();

            showModal(`${type === 'project' ? "Project" : "User"} deleted successfully`, "success");
        } catch (error) {
            showModal(errorMessage(error, "Failed to delete item"), "error");
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gray-50">
                <div className="animate-pulse flex flex-col items-center">
                    <div className="h-8 w-8 bg-green-500 rounded-full mb-4"></div>
                    <p className="text-gray-500">Loading Dashboard...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="w-full min-h-screen bg-[#F3F4F6]">
            {/* --- RENDER MODALS HERE --- */}
            {modalConfig && (
                <MessageModal 
                    message={modalConfig.message} 
                    type={modalConfig.type} 
                    onClose={() => setModalConfig(null)} 
                />
            )}

            <ConfirmModal 
                isOpen={confirmConfig.isOpen}
                title={confirmConfig.type === 'project' ? "Delete Project?" : "Delete User?"}
                message={confirmConfig.type === 'user'
                    ? "Their results, files and the private projects they own are deleted too. This cannot be undone."
                    : "This action cannot be undone. Are you sure?"}
                onConfirm={executeDelete}
                onCancel={() => setConfirmConfig({ ...confirmConfig, isOpen: false })}
            />
            {/* PROFESSIONAL HEADER */}
            <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 sm:h-20 flex items-center justify-between">
                    <div className="flex items-center gap-3 sm:gap-4 min-w-0">
                        <img src={wordmark} alt="OmniFox" className="h-6 sm:h-8 w-auto object-contain shrink-0" />
                        <div className="min-w-0">
                            <h1 className="text-lg sm:text-xl font-bold text-gray-900 leading-none truncate">Dashboard</h1>
                        </div>
                    </div>

                    <div className="flex items-center gap-2 sm:gap-3">
                        <button
                            onClick={() => navigate("/app")}
                            aria-label="Back to App"
                            className="flex items-center gap-2 px-3 sm:px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-50 rounded-lg transition-colors">
                            <AiOutlineArrowLeft aria-hidden="true" /> <span className="hidden sm:inline">Back to App</span>
                        </button>
                        <div className="h-6 w-px bg-gray-200 mx-2 hidden sm:block"></div>
                        <div className="flex items-center gap-2 sm:gap-3">
                            <div className="text-right hidden md:block">
                                <p className="text-sm font-medium text-gray-900 truncate max-w-[150px]">{user?.name}</p>
                                <p className="text-xs text-gray-500 truncate max-w-[150px]">{user?.email}</p>
                            </div>
                            <button onClick={handleLogout} className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors" title="Logout"
                                                        aria-label="Logout">
                                <AiOutlineLogout size={20} aria-hidden="true" />
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            {/* MAIN CONTENT CONTAINER */}
            <main id="main-content" tabIndex={-1} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-8 focus:outline-none">
                {/* MODERN TABS */}
                <div className="mb-6 sm:mb-8 overflow-x-auto">
                    <nav aria-label="Dashboard sections" className="flex space-x-2 min-w-max p-1 bg-white/50 rounded-xl border border-gray-200/60 backdrop-blur-sm">
                        {[
                            { id: "analytics", label: "Analytics", icon: <AiOutlineAreaChart />, condition: canViewAnalytics },
                            { id: "projects", label: "Projects", icon: <AiOutlineFolder />, condition: canManageProjects },
                            { id: "activity", label: "Audit Log", icon: <AiOutlineHistory />, condition: isAdmin },
                            { id: "users", label: "Team Members", icon: <AiOutlineUser />, condition: isAdmin },
                        ].map((tab) => {
                            if (tab.condition === false) return null;
                            const isActive = activeTab === tab.id;
                            return (
                                <button
                                    key={tab.id}
                                    onClick={() => setActiveTab(tab.id)}
                                    aria-pressed={isActive}
                                    aria-label={tab.label}
                                    className={`
                    flex items-center gap-2 px-3 sm:px-5 py-2.5 text-xs sm:text-sm font-medium rounded-lg transition-all duration-200 whitespace-nowrap
                    ${isActive ? "bg-white text-green-700 shadow-sm ring-1 ring-black/5" : "text-gray-500 hover:text-gray-700 hover:bg-gray-50/50"}
                  `}>
                                    {tab.icon}
                                    <span className="hidden sm:inline">{tab.label}</span>
                                    <span className="sm:hidden">{tab.label.split(" ")[0]}</span>
                                </button>
                            );
                        })}
                    </nav>
                </div>

                {/* TAB CONTENT AREA */}
                <div className="space-y-6">
                    {/* --- ANALYTICS TAB --- */}
                    {activeTab === "analytics" && canViewAnalytics && (
                        <div className="w-full">
                            <TabHeader title="Analytics" subtitle="Comments processed per project, for usage reporting and billing." />
                            <EnhancedDashboard />
                        </div>
                    )}

                    {/* --- AUDIT LOG TAB (admins) --- */}
                    {activeTab === "activity" && isAdmin && <AuditLogTab />}

{/* --- PROJECTS TAB (New) --- */}
{activeTab === "projects" && canManageProjects && (
                        <>
                            <TabHeader
                                title="Project Management"
                                subtitle={isAdmin
                                    ? "Add or remove shared projects. Private projects are visible only to their owner and the people they share with."
                                    : "Your projects are private: only you and the people you share them with can see them."}
                                action={
                                    <button
                                        onClick={() => setShowAddProject(!showAddProject)}
                                        className="flex items-center gap-2 px-3 py-2 text-sm font-medium bg-green-700 text-white rounded-lg hover:bg-green-800 transition-colors">
                                        {showAddProject ? "Cancel" : <><AiOutlinePlus /> Add Project</>}
                                    </button>
                                }
                            />

                            {/* Add Project Form */}
                            {showAddProject && (
                                <div className="mb-6">
                                    <DashboardCard className="p-4 bg-green-50 border-green-200">
                                        <form onSubmit={handleAddProject} className="flex flex-col gap-4">
                                            <div className="flex-1 w-full">
                                                <label htmlFor="project-name" className="block text-sm font-medium text-gray-700 mb-1">New Project Name</label>
                                                <input
                                                    id="project-name"
                                                    type="text"
                                                    required
                                                    value={newProjectName}
                                                    onChange={(e) => setNewProjectName(e.target.value)}
                                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500"
                                                    placeholder="e.g. Q4 Marketing Campaign"
                                                />
                                            </div>
                                            <div className="w-full">
                                                <label htmlFor="project-objectives" className="block text-sm font-medium text-gray-700 mb-1">Campaign objectives (one per line, up to 10)</label>
                                                <textarea
                                                    id="project-objectives"
                                                    rows={4}
                                                    value={newProjectObjectives}
                                                    onChange={(e) => setNewProjectObjectives(e.target.value)}
                                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500"
                                                    placeholder={"e.g. Raise awareness of the vaccination drive\nBuild trust in the health ministry"}
                                                />
                                            </div>
                                            {isAdmin && canCreatePrivate && (
                                                <label className="flex items-center gap-2 text-sm text-gray-700">
                                                    <input
                                                        type="checkbox"
                                                        checked={newProjectPrivate}
                                                        onChange={(e) => setNewProjectPrivate(e.target.checked)}
                                                    />
                                                    Private (only you and the people you share it with)
                                                </label>
                                            )}
                                            <button type="submit" className="w-full sm:w-auto px-4 py-2 bg-green-700 text-white rounded-lg font-medium hover:bg-green-800">
                                                Create Project
                                            </button>
                                        </form>
                                    </DashboardCard>
                                </div>
                            )}

                            {/* Private-project key status */}
                            {canCreatePrivate && keyStatus && !keyStatus.has_password && (
                                <p className="mb-6 p-4 text-sm bg-amber-50 border border-amber-200 rounded-xl text-amber-900">
                                    Private projects are locked with your password, and your account signs in with Google only. Ask an admin to invite you with an email and password account to use them.
                                </p>
                            )}
                            {keyStatus?.has_keys && keyStatus.has_password && !keyStatus.unlocked && (
                                <DashboardCard className="mb-6 p-4 bg-amber-50 border-amber-200">
                                    <form onSubmit={handleRecoverKey} className="flex flex-col gap-3">
                                        <p className="text-sm text-amber-900">
                                            Your private projects are locked. Sign in with your email and password to open them. If your password was reset, enter the recovery code you saved and your current password.
                                        </p>
                                        <div className="flex flex-col sm:flex-row gap-3">
                                            <input
                                                aria-label="Recovery code"
                                                value={recovery.code}
                                                onChange={(e) => setRecovery({ ...recovery, code: e.target.value })}
                                                placeholder="Recovery code"
                                                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg font-mono"
                                            />
                                            <input
                                                aria-label="Current password"
                                                type="password"
                                                value={recovery.password}
                                                onChange={(e) => setRecovery({ ...recovery, password: e.target.value })}
                                                placeholder="Current password"
                                                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg"
                                            />
                                            <button type="submit" className="px-4 py-2 bg-green-700 text-white rounded-lg font-medium hover:bg-green-800">
                                                Unlock
                                            </button>
                                        </div>
                                        <button type="button" onClick={handleResetKey} className="self-start text-sm text-amber-900 underline">
                                            I lost my recovery code
                                        </button>
                                    </form>
                                </DashboardCard>
                            )}

                            {/* Project List */}
                            <DashboardCard>
                                <ul className="divide-y divide-gray-100">
                                    {projects.length === 0 ? (
                                        <li className="p-8 text-center text-gray-500">No projects found. Create one to get started.</li>
                                    ) : (
                                        projects.map((p) => (
                                            <li key={p.id} className="p-4 flex items-center justify-between hover:bg-gray-50 transition-colors">
                                                <div className="flex items-center gap-4">
                                                    <div className="h-10 w-10 bg-blue-50 text-blue-600 rounded-lg flex items-center justify-center">
                                                        <AiOutlineFolder size={20} />
                                                    </div>
                                                    <div>
                                                        <p className="font-bold text-gray-900 flex items-center gap-1">
                                                            {p.name}
                                                            {p.is_private && <AiOutlineLock className="text-gray-500" title="Private" aria-label="Private" />}
                                                            {p.locked && <span className="text-xs font-normal text-amber-700">Locked</span>}
                                                        </p>
                                                        <p className="text-xs text-gray-500">ID: {p.id}</p>
                                                        {p.is_owner && p.shared_with.length > 0 && (
                                                            <p className="text-xs text-gray-500">Shared with {p.shared_with.join(", ")}</p>
                                                        )}
                                                        {p.objectives?.length > 0 && (
                                                            <ol className="mt-1 list-decimal list-inside text-sm text-gray-700">
                                                                {p.objectives.map((o) => <li key={o}>{o}</li>)}
                                                            </ol>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className="flex items-center">
                                                    {!p.locked && <button
                                                        onClick={() => setTrendsProject(p)}
                                                        className="p-2 text-gray-500 hover:text-green-700 hover:bg-green-50 rounded-lg transition-colors"
                                                        title="Trends"
                                                        aria-label="Trends">
                                                        <AiOutlineLineChart size={20} />
                                                    </button>}
                                                    {p.is_private && p.is_owner && !p.locked && (
                                                        <button
                                                            onClick={() => openShareProject(p)}
                                                            className="p-2 flex items-center gap-1 text-gray-500 hover:text-green-700 hover:bg-green-50 rounded-lg transition-colors"
                                                            title="Share Project"
                                                            aria-label="Share Project">
                                                            <AiOutlineShareAlt size={20} /><span className="text-sm">Share</span>
                                                        </button>
                                                    )}
                                                    {(p.is_private ? p.is_owner : isAdmin) && !p.locked && (
                                                        <button
                                                            onClick={() => openEditObjectives(p)}
                                                            className="p-2 text-gray-500 hover:text-green-700 hover:bg-green-50 rounded-lg transition-colors"
                                                            title="Edit Objectives"
                                                            aria-label="Edit Objectives">
                                                            <AiOutlineEdit size={20} />
                                                        </button>
                                                    )}
                                                    {(p.is_private ? p.is_owner : isAdmin) && (
                                                        <button
                                                            onClick={() => confirmDeleteProject(p.id)}
                                                            className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                                            title="Delete Project"
                                                            aria-label="Delete Project">
                                                            <AiOutlineDelete size={20} />
                                                        </button>
                                                    )}
                                                </div>
                                            </li>
                                        ))
                                    )}
                                </ul>
                            </DashboardCard>

                            {trendsProject && <ProjectTrends project={trendsProject} onClose={() => setTrendsProject(null)} />}

                            {editingProject && (
                                <Modal title={`Objectives for ${editingProject.name}`} onClose={() => setEditingProject(null)}>
                                    <form onSubmit={handleEditObjectives}>
                                        <label htmlFor="edit-objectives" className="block text-sm font-medium text-gray-700 mb-1">
                                            Campaign objectives (one per line, up to 10)
                                        </label>
                                        <textarea
                                            id="edit-objectives"
                                            rows={6}
                                            value={editObjectives}
                                            onChange={(e) => setEditObjectives(e.target.value)}
                                            className="w-full mb-2 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500"
                                        />
                                        <p className="mb-6 text-xs text-gray-500">Past results keep the objectives they were scored on.</p>
                                        <div className="flex flex-col sm:flex-row gap-3">
                                            <button
                                                type="button"
                                                onClick={() => setEditingProject(null)}
                                                className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm sm:text-base">
                                                Cancel
                                            </button>
                                            <button
                                                type="submit"
                                                className="flex-1 px-4 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800 text-sm sm:text-base">
                                                Save
                                            </button>
                                        </div>
                                    </form>
                                </Modal>
                            )}

                            {sharingProject && (
                                <Modal title={`Share ${sharingProject.name}`} onClose={() => setSharingProject(null)}>
                                    <form onSubmit={handleShareProject}>
                                        <label htmlFor="share-emails" className="block text-sm font-medium text-gray-700 mb-1">
                                            Emails of the people who can see this project (one per line)
                                        </label>
                                        <textarea
                                            id="share-emails"
                                            rows={4}
                                            value={shareEmails}
                                            onChange={(e) => setShareEmails(e.target.value)}
                                            className="w-full mb-6 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500"
                                            placeholder="colleague@in2-comms.com"
                                        />
                                        <div className="flex flex-col sm:flex-row gap-3">
                                            <button
                                                type="button"
                                                onClick={() => setSharingProject(null)}
                                                className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm sm:text-base">
                                                Cancel
                                            </button>
                                            <button
                                                type="submit"
                                                className="flex-1 px-4 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800 text-sm sm:text-base">
                                                Save
                                            </button>
                                        </div>
                                    </form>
                                </Modal>
                            )}
                        </>
                    )}


                    {/* --- USERS TAB --- */}
                    {activeTab === "users" && isAdmin && (
                        <>
                            <TabHeader
                                title="Team Members"
                                subtitle="Manage user access & roles."
                                action={
                                    <div className="flex gap-2">
                                    <button
                                        onClick={() => setShowCreateUser(!showCreateUser)}
                                        className="flex items-center gap-2 px-3 sm:px-4 py-2 text-sm font-medium border border-green-700 text-green-700 rounded-lg hover:bg-green-50 transition-all">
                                        {showCreateUser ? "Cancel" : <><AiOutlinePlus size={18} /> Create Account</>}
                                    </button>
                                    <button
                                        onClick={() => {
                                            setShowAddUser(!showAddUser);
                                            if (!showAddUser) {
                                                setGeneratedLink("");
                                                setNewUser({ email: "", name: "" });
                                            }
                                        }}
                                        className="flex items-center gap-2 px-3 sm:px-4 py-2 text-sm font-medium bg-green-700 text-white rounded-lg hover:bg-green-800 shadow-sm transition-all">
                                        {showAddUser ? (
                                            "Cancel"
                                        ) : (
                                            <>
                                                <AiOutlinePlus size={18} /> Invite User
                                            </>
                                        )}
                                    </button>
                                    </div>
                                }
                            />

                            {/* Invite Form Card */}
                            {showAddUser && (
                                <div className="mb-4 sm:mb-6">
                                    <DashboardCard className="p-4 sm:p-6 border-green-200 bg-green-50/30">
                                        <h3 className="font-bold text-gray-900 mb-4 text-sm sm:text-base">Invite New Team Member</h3>
                                        {generatedLink ? (
                                            <div className="bg-white p-3 sm:p-4 rounded-lg border border-green-200 shadow-sm">
                                                <p className="text-green-700 font-medium mb-2 text-sm">✅ Invitation Link Generated (valid for 24 hours)</p>
                                                <div className="flex flex-col sm:flex-row gap-2">
                                                    <input
                                                        readOnly
                                                        aria-label="Invitation link"
                                                        value={generatedLink}
                                                        className="flex-1 p-2 text-xs sm:text-sm border border-gray-200 rounded-md bg-gray-50 text-gray-600"
                                                    />
                                                    <button
                                                        onClick={() => {
                                                            navigator.clipboard.writeText(generatedLink);
                                                            showModal("Link copied to clipboard", "success");
                                                        }}
                                                        className="px-4 py-2 bg-green-700 text-white rounded-md text-sm font-medium hover:bg-green-800 whitespace-nowrap">
                                                        Copy
                                                    </button>
                                                </div>
                                                <button
                                                    onClick={() => {
                                                        setGeneratedLink("");
                                                        setNewUser({ email: "", name: "" });
                                                        setShowAddUser(false);
                                                    }}
                                                    className="mt-3 text-xs sm:text-sm text-gray-500 hover:text-gray-700 underline">
                                                    Done
                                                </button>
                                            </div>
                                        ) : (
                                            <form onSubmit={handleInviteUser} className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4 items-end">
                                                <div>
                                                    <label htmlFor="invite-email" className="block text-xs sm:text-sm font-medium text-gray-700 mb-1">Email Address</label>
                                                    <input
                                                        id="invite-email"
                                                        type="email"
                                                        required
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500/20 focus:border-green-500 text-sm"
                                                        placeholder="colleague@company.com"
                                                        value={newUser.email}
                                                        onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                                                    />
                                                </div>
                                                <div>
                                                    <label htmlFor="invite-name" className="block text-xs sm:text-sm font-medium text-gray-700 mb-1">Full Name</label>
                                                    <input
                                                        id="invite-name"
                                                        type="text"
                                                        required
                                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500/20 focus:border-green-500 text-sm"
                                                        placeholder="John Doe"
                                                        value={newUser.name}
                                                        onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
                                                    />
                                                </div>
                                                <button
                                                    type="submit"
                                                    className="w-full sm:w-auto px-4 sm:px-6 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800 font-medium transition-colors text-sm">
                                                    Generate Link
                                                </button>
                                            </form>
                                        )}
                                    </DashboardCard>
                                </div>
                            )}

                            {/* Create Account Form */}
                            {showCreateUser && (
                                <DashboardCard className="mb-4 sm:mb-6 p-4 sm:p-6 border-green-200 bg-green-50/30">
                                    <h3 className="font-bold text-gray-900 mb-1 text-sm sm:text-base">Create Account</h3>
                                    <p className="mb-4 text-xs sm:text-sm text-gray-600">They sign in with this temporary password and must choose their own straight away.</p>
                                    <form onSubmit={handleCreateUser} className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4 items-end">
                                        {[
                                            { key: "email", label: "Email Address", type: "email" },
                                            { key: "name", label: "Full Name", type: "text" },
                                            { key: "password", label: "Temporary Password", type: "text" },
                                        ].map((f) => (
                                            <div key={f.key}>
                                                <label htmlFor={`create-${f.key}`} className="block text-xs sm:text-sm font-medium text-gray-700 mb-1">{f.label}</label>
                                                <input
                                                    id={`create-${f.key}`}
                                                    type={f.type}
                                                    required
                                                    autoComplete="off"
                                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500/20 focus:border-green-500 text-sm"
                                                    value={createForm[f.key]}
                                                    onChange={(e) => setCreateForm({ ...createForm, [f.key]: e.target.value })}
                                                />
                                            </div>
                                        ))}
                                        <div>
                                            <label htmlFor="create-role" className="block text-xs sm:text-sm font-medium text-gray-700 mb-1">Role</label>
                                            <select
                                                id="create-role"
                                                value={createForm.role}
                                                onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
                                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm">
                                                {roles.map((role) => <option key={role.name} value={role.name}>{role.name}</option>)}
                                            </select>
                                        </div>
                                        <button
                                            type="submit"
                                            className="w-full sm:w-auto px-4 sm:px-6 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800 font-medium transition-colors text-sm">
                                            Create Account
                                        </button>
                                    </form>
                                </DashboardCard>
                            )}

                            {/* Join Requests */}
                            {joinRequests.length > 0 && (
                                <DashboardCard className="mb-4 sm:mb-6 border-amber-200">
                                    <h3 className="px-4 pt-4 font-bold text-gray-900 text-sm sm:text-base">Requests to join</h3>
                                    <ul className="divide-y divide-gray-100">
                                        {joinRequests.map((r) => (
                                            <li key={r.id} className="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                                <div className="min-w-0">
                                                    <p className="text-sm font-bold text-gray-900 truncate">{r.name}</p>
                                                    <p className="text-xs sm:text-sm text-gray-500 truncate">{r.email}</p>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <select
                                                        aria-label={`Role for ${r.email}`}
                                                        value={joinRoles[r.id] || "basic_user"}
                                                        onChange={(e) => setJoinRoles({ ...joinRoles, [r.id]: e.target.value })}
                                                        className="px-2 py-2 border border-gray-300 rounded-lg text-sm">
                                                        {roles.map((role) => <option key={role.name} value={role.name}>{role.name}</option>)}
                                                    </select>
                                                    <button
                                                        onClick={() => handleJoinRequest(r, true)}
                                                        className="px-3 py-2 bg-green-700 text-white rounded-lg text-sm font-medium hover:bg-green-800">
                                                        Accept
                                                    </button>
                                                    <button
                                                        onClick={() => handleJoinRequest(r, false)}
                                                        className="px-3 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-red-50 hover:text-red-700">
                                                        Reject
                                                    </button>
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                </DashboardCard>
                            )}

                            {/* Users List Card */}
                            <DashboardCard>
                                <ul className="divide-y divide-gray-100">
                                    {users.map((u) => (
                                        <li key={u.id} className="p-3 sm:p-4 hover:bg-gray-50 transition-colors">
                                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
                                                <div className="flex items-start gap-3 sm:gap-4 min-w-0 flex-1">
                                                    <div className="h-10 w-10 sm:h-12 sm:w-12 rounded-full bg-gradient-to-br from-green-100 to-green-50 flex items-center justify-center text-green-700 font-bold text-base sm:text-lg shrink-0">
                                                        {u.name?.[0]?.toUpperCase()}
                                                    </div>
                                                    <div className="min-w-0 flex-1">
                                                        <p className="text-sm font-bold text-gray-900 truncate">{u.name}</p>
                                                        <p className="text-xs sm:text-sm text-gray-500 truncate">{u.email}</p>
                                                        <div className="mt-2 flex flex-wrap gap-1">
                                                            {u.roles?.map((role) => (
                                                                <span
                                                                    key={role}
                                                                    className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-md text-xs font-medium border border-gray-200">
                                                                    {role}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>

                                                <div className="flex items-center gap-2 self-start sm:self-center">
                                                    <button
                                                        onClick={() => handleViewSessions(u)}
                                                        className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg border border-transparent hover:border-blue-200 transition-all"
                                                        title="View Sessions"
                                                        aria-label="View Sessions">
                                                        <AiOutlineDesktop size={18} />
                                                    </button>
                                                    {u.id !== user.id && <button
                                                        onClick={() => {
                                                            setEditingUser(u);
                                                            setSelectedRoles(u.roles || []);
                                                        }}
                                                        className="p-2 text-gray-500 hover:text-green-600 hover:bg-green-50 rounded-lg border border-transparent hover:border-green-200 transition-all"
                                                        title="Edit Roles"
                                                        aria-label="Edit Roles">
                                                        <AiOutlineEdit size={18} />
                                                    </button>}
                                                    <button
                                                        onClick={() => handleResetLink(u)}
                                                        className="p-2 text-gray-500 hover:text-green-600 hover:bg-green-50 rounded-lg border border-transparent hover:border-green-200 transition-all"
                                                        title="Reset Password"
                                                        aria-label="Reset Password">
                                                        <AiOutlineKey size={18} />
                                                    </button>
                                                    {u.id !== user.id && (
                                                        <button
                                                            onClick={() => confirmDeleteUser(u.id)}
                                                            className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg border border-transparent hover:border-red-200 transition-all"
                                                            title="Delete User"
                                                        aria-label="Delete User">
                                                            <AiOutlineDelete size={18} />
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            </DashboardCard>

                            {/* MODALS */}
                            {resetLink && (
                                <Modal title={`Reset link for ${resetLink.email}`} onClose={() => setResetLink(null)}>
                                    <p className="mb-3 text-sm text-gray-600">Send this link to them. It works once and expires in 24 hours. If they have private projects, they will need their recovery code to open them again.</p>
                                    <div className="flex flex-col sm:flex-row gap-2 mb-6">
                                        <input
                                            readOnly
                                            aria-label="Reset link"
                                            value={resetLink.link}
                                            className="flex-1 p-2 text-xs sm:text-sm border border-gray-200 rounded-md bg-gray-50 text-gray-600"
                                        />
                                        <button
                                            onClick={() => {
                                                navigator.clipboard.writeText(resetLink.link);
                                                showModal("Link copied to clipboard", "success");
                                            }}
                                            className="px-4 py-2 bg-green-700 text-white rounded-md text-sm font-medium hover:bg-green-800 whitespace-nowrap">
                                            Copy
                                        </button>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setResetLink(null)}
                                        className="w-full px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm sm:text-base">
                                        Close
                                    </button>
                                </Modal>
                            )}
                            {editingUser && (
                                <Modal title={`Edit Roles for ${editingUser.email}`} onClose={closeEditRoles}>
                                    <div className="space-y-3 mb-6">
                                        {roles.map((role) => (
                                            <label key={role.name} className="flex items-start p-3 border border-gray-100 rounded-lg hover:bg-gray-50 cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    checked={selectedRoles.includes(role.name)}
                                                    onChange={(e) => {
                                                        if (e.target.checked) {
                                                            setSelectedRoles([...selectedRoles, role.name]);
                                                        } else {
                                                            setSelectedRoles(selectedRoles.filter((r) => r !== role.name));
                                                        }
                                                    }}
                                                    className="h-4 w-4 accent-green-700 border-gray-300 rounded mt-0.5 shrink-0"
                                                />
                                                <div className="ml-3 min-w-0">
                                                    <span className="block text-sm font-medium text-gray-900">{role.name}</span>
                                                    <span className="block text-xs text-gray-500 mt-0.5">{role.description}</span>
                                                </div>
                                            </label>
                                        ))}
                                    </div>
                                    <div className="flex flex-col sm:flex-row gap-3">
                                        <button
                                            onClick={closeEditRoles}
                                            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm sm:text-base">
                                            Cancel
                                        </button>
                                        <button
                                            onClick={handleUpdateRoles}
                                            className="flex-1 px-4 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800 text-sm sm:text-base">
                                            Save Changes
                                        </button>
                                    </div>
                                </Modal>
                            )}

                            {viewingSessionsUser && (
                                <Modal title={`Sessions for ${viewingSessionsUser.email}`} onClose={() => setViewingSessionsUser(null)} className="max-w-2xl">
                                        <button
                                            onClick={() => setViewingSessionsUser(null)}
                                            aria-label="Close"
                                            className="absolute top-4 right-4 p-2 text-gray-500 hover:text-gray-700 text-xl leading-none">
                                            <span aria-hidden="true">×</span>
                                        </button>
                                        <p className="mb-3 text-sm text-gray-600">Devices and IP addresses are private to the user.</p>
                                        {sessionsError && <p role="alert" className="mb-3 text-sm text-red-700">{sessionsError}</p>}
                                        {userSessions.length === 0 ? (
                                            <p className="text-gray-500 text-center py-8 bg-gray-50 rounded-lg text-sm sm:text-base">No active sessions.</p>
                                        ) : (
                                            <ul className="space-y-3">
                                                {userSessions.map((s) => (
                                                    <li
                                                        key={s.id}
                                                        className="p-3 sm:p-4 bg-gray-50 rounded-lg border border-gray-200 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 sm:gap-4">
                                                        <div className="text-sm min-w-0 flex-1">
                                                            <p className="font-bold text-gray-900">Signed in {new Date(s.created_at).toLocaleDateString()}</p>
                                                            <p className="text-gray-500 text-xs sm:text-sm">
                                                                Last used {new Date(s.last_used).toLocaleString()}
                                                            </p>
                                                        </div>
                                                        <button
                                                            onClick={() => handleAdminRevokeSession(s.id)}
                                                            aria-label={`Sign out session last used ${new Date(s.last_used).toLocaleString()}`}
                                                            className="text-red-700 text-xs sm:text-sm font-medium hover:underline whitespace-nowrap">
                                                            Sign out
                                                        </button>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                </Modal>
                            )}
                        </>
                    )}
                </div>
            </main>
        </div>
    );
}

// System-wide audit log (admins). Each user's own activity is on their Profile.
function AuditLogTab() {
    const [activities, setActivities] = useState([]);
    const [loading, setLoading] = useState(false);
    const [filters, setFilters] = useState({ action: "", startDate: "", endDate: "" });
    const [availableActions, setAvailableActions] = useState([]);
    const [exportError, setExportError] = useState("");

    useEffect(() => {
        loadActivities();
        loadAvailableActions();
    }, [filters]);

    const loadActivities = async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams();
            if (filters.action) params.append("action", filters.action);
            if (filters.startDate) params.append("start_date", new Date(filters.startDate).toISOString());
            if (filters.endDate) {
                const endDate = new Date(filters.endDate);
                endDate.setHours(23, 59, 59, 999);
                params.append("end_date", endDate.toISOString());
            }
            const response = await api.get(`/activity-logs/all?${params.toString()}`);
            setActivities(response.data);
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
        }
    };
    const loadAvailableActions = async () => {
        try {
            const r = await api.get("/activity-logs/actions");
            setAvailableActions(r.data.actions);
        } catch {
            // The action filter is optional; the log still loads without it.
        }
    };
    const handleExport = async () => {
        setExportError("");
        try {
            const params = new URLSearchParams();
            if (filters.action) params.append("action", filters.action);
            if (filters.startDate) params.append("start_date", new Date(filters.startDate).toISOString());
            if (filters.endDate) {
                const endDate = new Date(filters.endDate);
                endDate.setHours(23, 59, 59, 999);
                params.append("end_date", endDate.toISOString());
            }
            const response = await api.get(`/activity-logs/all/export?${params.toString()}`, { responseType: "blob" });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement("a");
            link.href = url;
            link.setAttribute("download", "log.csv");
            document.body.appendChild(link);
            link.click();
            link.remove();
        } catch {
            setExportError("Export failed. Please try again.");
        }
    };

    return (
        <div className="space-y-4 sm:space-y-6">
            <TabHeader title="Audit Log" subtitle="Sign-ins, uploads and account changes across all users." />
            <DashboardCard className="p-3 sm:p-4">
                <div className="space-y-3 sm:space-y-4">
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
                        <div className="space-y-1">
                            <label htmlFor="activity-action" className="text-xs font-semibold text-gray-500">Action Type</label>
                            <select
                                id="activity-action"
                                value={filters.action}
                                onChange={(e) => setFilters({ ...filters, action: e.target.value })}
                                className="w-full text-xs sm:text-sm border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500">
                                <option value="">All Actions</option>
                                {availableActions.filter(Boolean).map((a) => (
                                    <option key={a} value={a}>
                                        {a.replaceAll("_", " ")}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="space-y-1">
                            <label htmlFor="activity-start" className="text-xs font-semibold text-gray-500">Start Date</label>
                            <input
                                id="activity-start"
                                type="date"
                                value={filters.startDate}
                                onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
                                className="w-full text-xs sm:text-sm border-gray-300 rounded-lg focus:ring-green-500"
                            />
                        </div>
                        <div className="space-y-1">
                            <label htmlFor="activity-end" className="text-xs font-semibold text-gray-500">End Date</label>
                            <input
                                id="activity-end"
                                type="date"
                                value={filters.endDate}
                                onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
                                className="w-full text-xs sm:text-sm border-gray-300 rounded-lg focus:ring-green-500"
                            />
                        </div>
                    </div>
                    <div className="flex flex-col sm:flex-row gap-2">
                        <button
                            onClick={() => setFilters({ action: "", startDate: "", endDate: "" })}
                            className="flex-1 px-3 py-2 text-xs sm:text-sm border border-gray-300 rounded-lg hover:bg-gray-50">
                            Clear
                        </button>
                        <button onClick={handleExport} className="flex-1 px-3 py-2 text-xs sm:text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-800">
                            Export CSV
                        </button>
                    </div>
                    {exportError && <p role="alert" className="text-sm text-red-700">{exportError}</p>}
                </div>
            </DashboardCard>

            <DashboardCard>
                <div className="bg-gray-50 px-3 sm:px-4 py-3 border-b border-gray-200">
                    <h2 className="text-xs sm:text-sm font-semibold text-gray-900">All users</h2>
                </div>
                <ul className="divide-y divide-gray-100 max-h-[500px] overflow-y-auto">
                    {loading ? (
                        <li className="p-4 text-center text-gray-500 text-xs sm:text-sm">Loading logs...</li>
                    ) : activities.length === 0 ? (
                        <li className="p-4 text-center text-gray-500 text-xs sm:text-sm">No records found.</li>
                    ) : (
                        activities.map((log) => (
                            <li key={log.id} className="p-3 sm:p-4 hover:bg-gray-50 transition-colors">
                                <div className="flex flex-col sm:flex-row gap-2 justify-between">
                                    <div className="min-w-0 flex-1">
                                        <p className="text-xs sm:text-sm font-medium text-gray-900 flex flex-wrap items-center gap-2">
                                          <span>{log.action?.replaceAll("_", " ")}</span>
                                          <span className="text-xs font-normal text-gray-600 bg-gray-100 px-1.5 rounded">{log.user_email}</span>
                                        </p>
                                    </div>
                                    <div className="text-left sm:text-right shrink-0">
                                        <p className="text-xs text-gray-500">{new Date(log.created_at).toLocaleDateString()}</p>
                                        <p className="text-xs text-gray-500">{new Date(log.created_at).toLocaleTimeString()}</p>
                                    </div>
                                </div>
                            </li>
                        ))
                    )}
                </ul>
            </DashboardCard>
        </div>
    );
}