import { useState } from "react";
import { downloadFile } from "../services/authService";
import PropTypes from "prop-types";
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";

const Graphs = ({ downloadLink, sentimentCounts, positiveContext, neutralContext, negativeContext, overallSummary, objectiveResults = [], totalComments, skippedComments, onReset }) => {
    const [downloadError, setDownloadError] = useState(null);

    // Safely extract counts with fallbacks for any key format
    const getSentimentCount = (sentimentType) => {
        // Convert input to lowercase for comparison
        const type = sentimentType.toLowerCase();

        // Check if sentimentCounts is defined
        if (!sentimentCounts) return 0;

        // Try direct match with lowercase key
        if (sentimentCounts[type] !== undefined) {
            return sentimentCounts[type];
        }

        // Try with first letter capitalized
        const capitalizedType = type.charAt(0).toUpperCase() + type.slice(1);
        if (sentimentCounts[capitalizedType] !== undefined) {
            return sentimentCounts[capitalizedType];
        }

        // Try with all uppercase
        const upperType = type.toUpperCase();
        if (sentimentCounts[upperType] !== undefined) {
            return sentimentCounts[upperType];
        }

        // Case-insensitive search
        for (const [key, value] of Object.entries(sentimentCounts)) {
            if (key.toLowerCase() === type) {
                return value;
            }
        }

        // Default to 0 if not found
        return 0;
    };

    // Calculate percentages
       const calculatePercentage = (count) => {
        return totalComments > 0 ? ((count / totalComments) * 100).toFixed(1) : 0;
      };

    // Get counts for each sentiment type
    const positiveCount = getSentimentCount("positive");
    const neutralCount = getSentimentCount("neutral");
    const negativeCount = getSentimentCount("negative");

    // Calculate percentages
    const positivePercentage = calculatePercentage(positiveCount);
    const neutralPercentage = calculatePercentage(neutralCount);
    const negativePercentage = calculatePercentage(negativeCount);

    const pieData = [
        { name: "Aligned", value: Number(positivePercentage), color: "#2E7D38" },
        { name: "Neutral", value: Number(neutralPercentage), color: "#666666" },
        { name: "Not aligned", value: Number(negativePercentage), color: "#C9443B" },
    ];


    return (
        <section aria-labelledby="results-heading" className="flex flex-col items-center space-y-5 mt-5 w-full">
            <h2 id="results-heading" className="text-2xl font-semibold text-gray-800">Analysis results</h2>
            {skippedComments > 0 && (
                <p role="status" className="w-full max-w-3xl text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-lg p-3 text-center">
                    {skippedComments} of {totalComments + skippedComments} comments could not be analyzed and are not included in these results or the file.
                </p>
            )}
            {/* Sentiment counts */}
            <dl className="flex flex-wrap justify-center gap-4 w-full">
                {[
                    { label: "Total Comments", value: totalComments || 0, bg: "bg-white", text: "text-black" },
                    { label: "Aligned Comments", value: positiveCount, bg: "bg-[#2E7D38]", text: "text-white" },
                    { label: "Neutral Comments", value: neutralCount, bg: "bg-[#666666]", text: "text-white" },
                    { label: "Not Aligned Comments", value: negativeCount, bg: "bg-[#C9443B]", text: "text-white" },
                ].map(({ label, value, bg, text }) => (
                    <div key={label} className={`w-[160px] p-4 ${bg} ${text} rounded-lg shadow-md text-center flex flex-col-reverse`}>
                        <dt className="text-xs">{label}</dt>
                        <dd className="font-bold text-lg">{value}</dd>
                    </div>
                ))}
            </dl>


            {/* Graph: the counts above are its text alternative */}
            <p className="sr-only">
                Sentiment share: {positivePercentage}% aligned, {neutralPercentage}% neutral, {negativePercentage}% not aligned.
            </p>
            <div className="flex justify-center w-full">
                <div className="w-full max-w-lg bg-gray-100 rounded-lg p-4 sm:p-8 shadow-md">
                    {/* Responsive: fits narrow phones (the old chart was a fixed 400 px). */}
                    <div className="h-[240px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart title="Sentiment share" desc="Aligned, neutral and not aligned share of analyzed comments.">
                                <Pie data={pieData} dataKey="value" nameKey="name" outerRadius="70%" isAnimationActive={false} label={({ value }) => `${value}%`}>
                                    {pieData.map((slice) => (
                                        <Cell key={slice.name} fill={slice.color} />
                                    ))}
                                </Pie>
                                <Tooltip formatter={(value) => `${value}%`} />
                                <Legend />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
   {overallSummary && (
      <section aria-labelledby="overall-summary-heading" className="w-full max-w-3xl mb-4 p-4 bg-white border border-gray-200 rounded-lg shadow-sm">
        <h3 id="overall-summary-heading" className="font-bold text-lg text-gray-900 mb-2">Overall summary</h3>
        <p dir="auto" className="text-sm text-gray-800">{overallSummary}</p>
      </section>
   )}
   {objectiveResults.length > 0 && (
      <section aria-labelledby="objectives-heading" className="w-full max-w-3xl mb-4 p-4 bg-white border border-gray-200 rounded-lg shadow-sm">
        <h3 id="objectives-heading" className="font-bold text-lg text-gray-900 mb-2">Campaign objectives</h3>
        <ul className="divide-y divide-gray-100">
          {objectiveResults.map((o) => (
            <li key={o.objective} className="py-3">
              <p dir="auto" className="font-semibold text-gray-900">{o.objective}</p>
              <p className="text-sm text-gray-700 my-1">
                {o.percent_met === null
                  ? "No comments addressed this objective."
                  : `${o.percent_met}% met · average alignment ${o.average_alignment} · ${o.supports} supporting, ${o.neutral} neutral, ${o.against} against (${o.relevant_comments} relevant)`}
              </p>
              <p dir="auto" className="text-sm text-gray-800">{o.summary}</p>
            </li>
          ))}
        </ul>
      </section>
   )}
   {/* Larger Divs - Context */}
   <div className="grid grid-cols-1 md:grid-cols-3 gap-4 w-full max-w-3xl">
        {[
          { title: "Aligned Context", text: positiveContext, bg: "bg-[#2E7D38]" },
          { title: "Neutral Context", text: neutralContext, bg: "bg-[#666666]" },
          { title: "Not Aligned Context", text: negativeContext, bg: "bg-[#C9443B]" }
        ].map(({ title, text, bg }, index) => (
          <div key={index} className={`p-4 ${bg} text-white rounded-lg shadow-md text-center`}>
            <h3 className="font-bold text-lg mb-2">{title}</h3>
            <p className="text-sm">{text}</p>
          </div>
        ))}
      </div>
            {downloadLink && (
                <button
                    onClick={async () => setDownloadError(await downloadFile(downloadLink))}
                    className="mt-6 bg-[#2E7D38] text-white font-semibold py-2 px-4 rounded-lg hover:bg-[#256A2E]"
                >
                    Download Processed File
                </button>
            )}
            {downloadError && <p role="alert" className="text-sm text-red-700 text-center max-w-md">{downloadError}</p>}
            {onReset && (
                <button
                    onClick={onReset}
                    className="border border-gray-300 text-gray-700 font-semibold py-2 px-4 rounded-lg hover:bg-gray-50"
                >
                    Analyze another file or URL
                </button>
            )}

        </section>
    );
};

Graphs.propTypes = {
    downloadLink: PropTypes.string,
    sentimentCounts: PropTypes.object,
    positiveContext: PropTypes.string,
    neutralContext: PropTypes.string,
    negativeContext: PropTypes.string,
    overallSummary: PropTypes.string,
    objectiveResults: PropTypes.arrayOf(PropTypes.shape({
        objective: PropTypes.string,
        relevant_comments: PropTypes.number,
        supports: PropTypes.number,
        neutral: PropTypes.number,
        against: PropTypes.number,
        percent_met: PropTypes.number,
        average_alignment: PropTypes.number,
        summary: PropTypes.string,
    })),
    totalComments: PropTypes.number,
    skippedComments: PropTypes.number,
    onReset: PropTypes.func,
};

// Default props
Graphs.defaultProps = {
    sentimentCounts: {},
    totalComments: 0,
    positiveContext: "",
    neutralContext: "",
    negativeContext: ""
};

export default Graphs;