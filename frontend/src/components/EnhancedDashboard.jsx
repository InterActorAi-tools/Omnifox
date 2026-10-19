import { useState, useEffect } from "react";
import api from "../services/authService";
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";
import { Activity, Users, TrendingUp, RefreshCw, Calendar, Filter } from "lucide-react";

const EnhancedDashboard = () => {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState(null);
    const [dateFilter, setDateFilter] = useState("last_30_days");
    const [customDateRange, setCustomDateRange] = useState({
        startDate: "",
        endDate: "",
    });
    const [showCustomDate, setShowCustomDate] = useState(false);
    const [timeSeriesData, setTimeSeriesData] = useState([]);

    // Date filter presets
    const datePresets = [
        { key: "last_7_days", label: "7 Days" },
        { key: "last_30_days", label: "30 Days" },
        { key: "last_60_days", label: "60 Days" },
        { key: "last_90_days", label: "90 Days" },
        { key: "this_month", label: "This Month" },
        { key: "last_month", label: "Last Month" },
        { key: "custom", label: "Custom" },
    ];

    useEffect(() => {
        fetchStats();
    }, [dateFilter, customDateRange]);

    const fetchStats = async () => {
        try {
            setLoading(true);

            const params = {};
            if (dateFilter === "custom" && customDateRange.startDate && customDateRange.endDate) {
                params.start_date = customDateRange.startDate;
                params.end_date = customDateRange.endDate;
            } else if (dateFilter !== "custom") {
                params.preset = dateFilter;
            }

            const { data } = await api.get("/analytics/simple-stats", { params });
            setStats(data);
            setTimeSeriesData(data.time_series_data || []);
            setLastUpdated(new Date());
        } catch (error) {
            console.error("Error fetching stats:", error);
        } finally {
            setLoading(false);
        }
    };

    const handleDateFilterChange = (newFilter) => {
        setDateFilter(newFilter);
        setShowCustomDate(newFilter === "custom");

        if (newFilter !== "custom") {
            setCustomDateRange({ startDate: "", endDate: "" });
        }
    };

    const handleCustomDateChange = (field, value) => {
        setCustomDateRange((prev) => ({
            ...prev,
            [field]: value,
        }));
    };

    const formatDateRange = (dateRange) => {
        if (!dateRange) return "All time";

        const start = new Date(dateRange.start_date).toLocaleDateString();
        const end = new Date(dateRange.end_date).toLocaleDateString();
        const days = dateRange.total_days;

        return `${start} - ${end} (${Math.round(days)} days)`;
    };


    if (loading && !stats) {
        return (
            <div className="min-h-screen bg-gray-50 p-4 sm:p-6 flex items-center justify-center">
                <div className="text-center">
                    <RefreshCw className="w-8 h-8 animate-spin text-green-700 mx-auto mb-4" />
                    <p className="text-gray-600">Loading analytics...</p>
                </div>
            </div>
        );
    }

    const colors = ["#3B9846", "#2F7B3B", "#4CAF50", "#66BB6A", "#81C784"];

    // Prepare chart data
    const chartData = stats
        ? stats.project_breakdown.map((project, index) => ({
              ...project,
              color: colors[index % colors.length],
          }))
        : [];

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Toolbar: selected period + refresh */}
            <div className="bg-white shadow-sm">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <p className="text-sm text-gray-700">
                        {stats?.date_range ? <>Showing <strong>{formatDateRange(stats.date_range)}</strong></> : "Loading period…"}
                    </p>
                    <button
                        onClick={fetchStats}
                        disabled={loading}
                        className="self-start sm:self-auto font-semibold py-2 px-4 rounded-lg flex items-center justify-center gap-2 bg-[#2E7D38] hover:bg-[#256A2E] text-white disabled:opacity-60">
                        <RefreshCw aria-hidden="true" className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
                        Refresh
                    </button>
                </div>
            </div>

            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
                {/* Date Filter Controls */}
                <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm mb-4 sm:mb-6">
                    <div className="flex items-center gap-4 mb-4">
                        <Filter aria-hidden="true" className="w-5 h-5 text-gray-600" />
                        <h3 className="text-base sm:text-lg font-semibold text-gray-900">Date Range Filter</h3>
                    </div>

                    <div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-2 sm:gap-3 mb-4">
                            {datePresets.map((preset) => (
                                <button
                                    key={preset.key}
                                    onClick={() => handleDateFilterChange(preset.key)}
                                    aria-pressed={dateFilter === preset.key}
                                    className={`px-2 sm:px-3 py-2 rounded-lg text-xs sm:text-sm font-medium transition-colors ${
                                        dateFilter === preset.key ? "bg-[#2E7D38] text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                                    }`}>
                                    {preset.label}
                                </button>
                            ))}
                        </div>

                        {showCustomDate && (
                            <div className="p-4 bg-gray-50 rounded-lg">
                                <Calendar aria-hidden="true" className="w-5 h-5 text-gray-600 mb-3" />
                                <div className="flex flex-col sm:flex-row items-start sm:items-end gap-3">
                                    <div className="w-full sm:w-auto">
                                        <label htmlFor="analytics-start" className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
                                        <input
                                            id="analytics-start"
                                            type="date"
                                            value={customDateRange.startDate}
                                            onChange={(e) => handleCustomDateChange("startDate", e.target.value)}
                                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                                        />
                                    </div>
                                    <div className="w-full sm:w-auto">
                                        <label htmlFor="analytics-end" className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
                                        <input
                                            id="analytics-end"
                                            type="date"
                                            value={customDateRange.endDate}
                                            onChange={(e) => handleCustomDateChange("endDate", e.target.value)}
                                            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                                        />
                                    </div>
                                    <button
                                        onClick={fetchStats}
                                        disabled={!customDateRange.startDate || !customDateRange.endDate || loading}
                                        className="w-full sm:w-auto bg-green-700 text-white px-4 py-2 rounded-lg hover:bg-green-800 disabled:bg-gray-400 text-sm font-medium">
                                        Apply
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {stats && (
                    <>
                        {/* Summary Cards */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6 mb-6 sm:mb-8">
                            <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium text-gray-600">Total Comments</p>
                                        <p className="text-2xl sm:text-3xl font-bold text-green-700">{stats.total_comments_processed.toLocaleString()}</p>
                                    </div>
                                    <Activity className="w-6 h-6 sm:w-8 sm:h-8 text-green-700" />
                                </div>
                            </div>

                            <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium text-gray-600">Total Operations</p>
                                        <p className="text-2xl sm:text-3xl font-bold text-blue-600">{stats.total_operations}</p>
                                    </div>
                                    <TrendingUp className="w-6 h-6 sm:w-8 sm:h-8 text-blue-600" />
                                </div>
                            </div>

                            <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm sm:col-span-2 lg:col-span-1">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium text-gray-600">Active Projects</p>
                                        <p className="text-2xl sm:text-3xl font-bold text-purple-600">{stats.total_projects}</p>
                                    </div>
                                    <Users className="w-6 h-6 sm:w-8 sm:h-8 text-purple-600" />
                                </div>
                            </div>
                        </div>

                        {/* Time Series Chart */}
                        {timeSeriesData.length > 0 && (
                            <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm mb-4 sm:mb-6">
                                <h3 className="text-base sm:text-lg font-semibold text-gray-900 mb-4">Activity Over Time</h3>
                                {/* Text alternative for the chart (WCAG 1.1.1) */}
                                <table className="sr-only">
                                    <caption>Comments and operations per period</caption>
                                    <thead>
                                        <tr><th scope="col">Period</th><th scope="col">Comments</th><th scope="col">Operations</th></tr>
                                    </thead>
                                    <tbody>
                                        {timeSeriesData.map((point) => (
                                            <tr key={point.date}><td>{point.date}</td><td>{point.comments}</td><td>{point.operations}</td></tr>
                                        ))}
                                    </tbody>
                                </table>
                                <div className="h-[250px] sm:h-[300px]">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={timeSeriesData} title="Activity over time" desc="Comments per period; the same figures are in the table above.">
                                            <CartesianGrid strokeDasharray="3 3" />
                                            <XAxis dataKey="date" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={60} />
                                            <YAxis tick={{ fontSize: 10 }} />
                                            <Tooltip formatter={(value, name) => [value.toLocaleString(), name]} labelFormatter={(label) => `Date: ${label}`} />
                                            <Line
                                                isAnimationActive={false}
                                                type="monotone"
                                                dataKey="comments"
                                                stroke="#3B9846"
                                                strokeWidth={2}
                                                name="Comments"
                                                dot={{ fill: "#3B9846", strokeWidth: 2, r: 3 }}
                                            />
                                            <Line
                                                isAnimationActive={false}
                                                type="monotone"
                                                dataKey="operations"
                                                stroke="#2563eb"
                                                strokeWidth={2}
                                                name="Operations"
                                                dot={{ fill: "#2563eb", strokeWidth: 2, r: 2 }}
                                            />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        )}

                        {/* Charts Section */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 mb-6 sm:mb-8">
                            {/* Bar Chart */}
                            <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm">
                                <h3 className="text-base sm:text-lg font-semibold text-gray-900 mb-4">Comments by Project</h3>
                                <p className="sr-only">Chart of the per-project figures listed in the Detailed Project Usage table below.</p>
                                <div className="h-[250px] sm:h-[300px]">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <BarChart data={chartData} title="Comments by project" desc="Per-project figures are listed in the Detailed Project Usage table.">
                                            <CartesianGrid strokeDasharray="3 3" />
                                            <XAxis dataKey="project" tick={{ fontSize: 9 }} angle={-45} textAnchor="end" height={60} />
                                            <YAxis tick={{ fontSize: 10 }} />
                                            <Tooltip formatter={(value) => [value.toLocaleString(), "Comments"]} />
                                            <Bar dataKey="total_comments" fill="#2E7D38" isAnimationActive={false} />
                                        </BarChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            {/* Pie Chart */}
                            <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm">
                                <h3 className="text-base sm:text-lg font-semibold text-gray-900 mb-4">Usage Distribution</h3>
                                <p className="sr-only">Chart of each project&apos;s share of comments; the percentages are listed in the Detailed Project Usage table below.</p>
                                <div className="h-[250px] sm:h-[300px]">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <PieChart title="Usage distribution" desc="Each project's share of comments; percentages are in the Detailed Project Usage table.">
                                            <Pie
                                                isAnimationActive={false}
                                                data={chartData}
                                                cx="50%"
                                                cy="50%"
                                                labelLine={false}
                                                label={({ project, percentage }) => `${project}: ${percentage}%`}
                                                outerRadius={window.innerWidth < 640 ? 60 : 80}
                                                fill="#8884d8"
                                                dataKey="total_comments">
                                                {chartData.map((entry, index) => (
                                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                                ))}
                                            </Pie>
                                            <Tooltip formatter={(value) => [value.toLocaleString(), "Comments"]} />
                                        </PieChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        </div>

                        {/* Operation Type Distribution */}
                        <div className="bg-white p-4 sm:p-6 rounded-lg shadow-sm mb-6 sm:mb-8">
                            <h3 className="text-base sm:text-lg font-semibold text-gray-900 mb-4">Operation Types Breakdown</h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                                {chartData.map((project) => (
                                    <div key={project.project} className="rounded-lg p-4 bg-gray-50">
                                        <h4 className="font-semibold text-gray-900 mb-3 text-sm sm:text-base truncate">{project.project}</h4>
                                        <div className="space-y-2">
                                            <div className="flex justify-between items-center">
                                                <span className="text-xs sm:text-sm text-gray-600">File Uploads:</span>
                                                <span className="font-semibold text-green-700 text-sm">{project.file_uploads}</span>
                                            </div>
                                            <div className="flex justify-between items-center">
                                                <span className="text-xs sm:text-sm text-gray-600">URL Extractions:</span>
                                                <span className="font-semibold text-blue-600 text-sm">{project.url_extractions}</span>
                                            </div>
                                            <div className="flex justify-between items-center">
                                                <span className="text-xs sm:text-sm text-gray-600">Total Operations:</span>
                                                <span className="font-semibold text-gray-900 text-sm">{project.operations}</span>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Project Breakdown Table */}
                        <div className="bg-white rounded-lg shadow-sm overflow-hidden mb-6 sm:mb-8">
                            <div className="px-4 sm:px-6 py-4 bg-gray-50">
                                <h3 id="project-usage-heading" className="text-base sm:text-lg font-semibold text-gray-900">Detailed Project Usage</h3>
                            </div>
                            {/* Scrolls sideways on small screens: focusable so keyboard users can scroll it. */}
                            <div className="overflow-x-auto" role="region" aria-labelledby="project-usage-heading" tabIndex={0}>
                                <table className="min-w-full divide-y divide-gray-200">
                                    <caption className="sr-only">Comments, share and operations per project for the selected period</caption>
                                    <thead className="bg-gray-50">
                                        <tr>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Rank</th>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Project</th>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Comments</th>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Percentage</th>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden sm:table-cell">
                                                Operations
                                            </th>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden md:table-cell">Files</th>
                                            <th scope="col" className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden md:table-cell">URLs</th>
                                        </tr>
                                    </thead>
                                    <tbody className="bg-white divide-y divide-gray-200">
                                        {stats.project_breakdown.map((project, index) => (
                                            <tr key={project.project} className="hover:bg-gray-50">
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap">
                                                    <span
                                                        className={`inline-flex items-center justify-center w-6 h-6 sm:w-8 sm:h-8 rounded-full text-xs sm:text-sm font-bold text-white ${
                                                            index === 0 ? "bg-yellow-500" : index === 1 ? "bg-gray-400" : index === 2 ? "bg-orange-600" : "bg-gray-300"
                                                        }`}>
                                                        {index + 1}
                                                    </span>
                                                </td>
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap">
                                                    <div className="font-medium text-gray-900 text-xs sm:text-sm truncate max-w-[100px] sm:max-w-none">{project.project}</div>
                                                </td>
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap">
                                                    <div className="text-sm sm:text-lg font-semibold text-green-700">{project.total_comments.toLocaleString()}</div>
                                                </td>
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap">
                                                    <div className="flex items-center">
                                                        <div className="flex-1 bg-gray-200 rounded-full h-2 mr-2 sm:mr-3 min-w-[40px]">
                                                            <div className="bg-green-700 h-2 rounded-full" style={{ width: `${Math.min(project.percentage, 100)}%` }}></div>
                                                        </div>
                                                        <span className="text-xs sm:text-sm font-medium text-gray-900">{project.percentage}%</span>
                                                    </div>
                                                </td>
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap text-xs sm:text-sm text-gray-900 hidden sm:table-cell">{project.operations}</td>
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap text-xs sm:text-sm text-gray-900 hidden md:table-cell">
                                                    {project.file_uploads}
                                                </td>
                                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap text-xs sm:text-sm text-gray-900 hidden md:table-cell">
                                                    {project.url_extractions}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* Summary Box */}
                        <div className="bg-green-50 rounded-lg p-4 sm:p-6">
                            <h3 className="text-base sm:text-lg font-semibold text-green-900 mb-3">📊 Period Summary</h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                                <div>
                                    <span className="font-medium text-green-800">Most Active Project:</span>
                                    <br />
                                    <span className="text-green-700 text-xs sm:text-sm">
                                        {stats.project_breakdown[0]?.project} ({stats.project_breakdown[0]?.percentage}%)
                                    </span>
                                </div>
                                <div>
                                    <span className="font-medium text-green-800">Average per Project:</span>
                                    <br />
                                    <span className="text-green-700 text-xs sm:text-sm">
                                        {Math.round(stats.total_comments_processed / stats.total_projects).toLocaleString()} comments
                                    </span>
                                </div>
                                <div>
                                    <span className="font-medium text-green-800">Comments per Operation:</span>
                                    <br />
                                    <span className="text-green-700 text-xs sm:text-sm">{Math.round(stats.total_comments_processed / stats.total_operations)} avg</span>
                                </div>
                                <div>
                                    <span className="font-medium text-green-800">Date Range:</span>
                                    <br />
                                    <span className="text-green-700 text-xs sm:text-sm">{Math.round(stats.date_range?.total_days || 0)} days</span>
                                </div>
                            </div>
                        </div>
                    </>
                )}

                {/* Footer */}
                <div className="mt-6 sm:mt-8 text-center text-xs sm:text-sm text-gray-500">
                    Last updated: {lastUpdated ? lastUpdated.toLocaleString() : "Never"} | Admin Dashboard - Authorized personnel only
                </div>
            </div>
        </div>
    );
};

export default EnhancedDashboard;