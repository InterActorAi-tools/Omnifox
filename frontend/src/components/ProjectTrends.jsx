import { useEffect, useState } from "react";
import PropTypes from "prop-types";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api, { errorMessage } from "../services/authService";
import Modal from "./Modal";

const SENTIMENT_LINES = [
    { key: "positive_percent", name: "Positive", color: "#2E7D38" },
    { key: "neutral_percent", name: "Neutral", color: "#666666" },
    { key: "negative_percent", name: "Negative", color: "#C9443B" },
];
const OBJECTIVE_COLORS = ["#2563EB", "#EA580C", "#7C3AED", "#0D9488", "#DB2777", "#CA8A04", "#4B5563", "#65A30D", "#0891B2", "#9F1239"];
const TREND_LABELS = { rising: "▲ Rising", falling: "▼ Falling", steady: "● Steady" };
const TREND_COLORS = { rising: "text-green-700", falling: "text-red-600", steady: "text-gray-600" };

const percent = (value) => (value === null || value === undefined ? "–" : `${value}%`);

const Trend = ({ trend }) =>
    trend ? <span className={`font-medium ${TREND_COLORS[trend]}`}>{TREND_LABELS[trend]}</span>
          : <span className="text-gray-400">Needs 2 uploads</span>;

Trend.propTypes = { trend: PropTypes.string };

const TrendChart = ({ title, data, lines }) => (
    <div className="mb-6">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">{title}</h3>
        <ResponsiveContainer width="100%" height={240}>
            <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 10 }} />
                <Tooltip formatter={(value) => percent(value)} />
                <Legend />
                {lines.map((l) => (
                    <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={2} connectNulls dot />
                ))}
            </LineChart>
        </ResponsiveContainer>
    </div>
);

TrendChart.propTypes = {
    title: PropTypes.string.isRequired,
    data: PropTypes.array.isRequired,
    lines: PropTypes.array.isRequired,
};

export default function ProjectTrends({ project, onClose }) {
    const [trends, setTrends] = useState(null);
    const [error, setError] = useState("");

    useEffect(() => {
        api.get(`/projects/${project.id}/trends`)
            .then((res) => setTrends(res.data))
            .catch((err) => setError(errorMessage(err, "Could not load the trends")));
    }, [project.id]);

    // One point per upload; objectives become obj0, obj1, ... for the chart.
    const data = (trends?.uploads || []).map((u, i) => ({
        ...u,
        label: `${new Date(u.date).toLocaleDateString()} (#${i + 1})`,
        ...Object.fromEntries(u.objectives.map((v, k) => [`obj${k}`, v])),
    }));
    const objectiveLines = (trends?.objectives || []).map((o, k) => ({
        key: `obj${k}`, name: `Objective ${k + 1}`, color: OBJECTIVE_COLORS[k % OBJECTIVE_COLORS.length],
    }));

    return (
        <Modal title={`Trends: ${project.name}`} onClose={onClose} className="max-w-4xl">
            {error && <p className="text-red-600 mb-4">{error}</p>}
            {!trends && !error && <p className="text-gray-500">Loading…</p>}
            {trends && trends.overall.uploads === 0 && (
                <p className="text-gray-500 mb-4">No uploads yet. Trends appear once comments are analysed for this project.</p>
            )}
            {trends && trends.overall.uploads > 0 && (
                <>
                    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
                        {[
                            ["Uploads", trends.overall.uploads],
                            ["Comments", trends.overall.comments],
                            ["Positive", percent(trends.overall.positive_percent)],
                            ["Negative", percent(trends.overall.negative_percent)],
                            ["Positive trend", <Trend key="t" trend={trends.overall.sentiment_trend} />],
                        ].map(([label, value]) => (
                            <div key={label} className="p-3 bg-gray-50 rounded-lg border border-gray-100">
                                <p className="text-xs text-gray-500">{label}</p>
                                <p className="text-lg font-bold text-gray-900">{value}</p>
                            </div>
                        ))}
                    </div>

                    <TrendChart title="Sentiment per upload" data={data} lines={SENTIMENT_LINES} />

                    {objectiveLines.length > 0 && (
                        <>
                            <TrendChart title="Objectives met per upload" data={data} lines={objectiveLines} />
                            <table className="w-full text-sm mb-4">
                                <thead>
                                    <tr className="text-left text-gray-500 border-b">
                                        <th className="py-2">Objective</th>
                                        <th className="py-2">Met overall</th>
                                        <th className="py-2">Latest upload</th>
                                        <th className="py-2">Trend</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {trends.objectives.map((o, k) => (
                                        <tr key={o.objective} className="border-b border-gray-100">
                                            <td className="py-2 pr-2">
                                                <span className="font-medium" style={{ color: objectiveLines[k].color }}>{k + 1}.</span> {o.objective}
                                            </td>
                                            <td className="py-2">{percent(o.percent_met)}</td>
                                            <td className="py-2">{percent(o.latest)}</td>
                                            <td className="py-2"><Trend trend={o.trend} /></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <p className="text-xs text-gray-500">
                                Met = share of the comments relevant to an objective that support it. The trend compares the latest upload with the first.
                            </p>
                        </>
                    )}
                </>
            )}
        </Modal>
    );
}

ProjectTrends.propTypes = {
    project: PropTypes.shape({ id: PropTypes.number.isRequired, name: PropTypes.string.isRequired }).isRequired,
    onClose: PropTypes.func.isRequired,
};
