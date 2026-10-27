import { useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { authService, errorMessage } from '../services/authService';

const SUMMARY_LABELS = { overall: "Overall", positive: "Aligned", neutral: "Neutral", negative: "Not aligned" };

const label = ({ sentiment, category }) => `${SUMMARY_LABELS[sentiment] || sentiment} · ${category}`;

function Proposal({ proposal, busy, onApply, onDismiss }) {
    const relabel = proposal.type === "relabel";
    return (
        <div className="border border-green-200 bg-green-50 rounded-lg p-3 text-sm text-gray-800">
            {relabel ? (
                <>
                    <p className="font-semibold">Proposed label changes ({proposal.changes.length})</p>
                    {proposal.reason && <p dir="auto" className="mb-2">{proposal.reason}</p>}
                    <ul className="space-y-1 max-h-60 overflow-y-auto">
                        {proposal.changes.map((c) => (
                            <li key={c.id}>
                                <span dir="auto">“{c.translation}”</span>{" "}
                                <span className="text-gray-600">{label(c.from)} → </span>
                                <span className="font-medium">{label(c.to)}</span>
                            </li>
                        ))}
                    </ul>
                    <p className="mt-2 text-gray-600">Applying updates the report and rewrites the summaries.</p>
                </>
            ) : (
                <>
                    <p className="font-semibold mb-2">Proposed summaries</p>
                    <dl className="space-y-2">
                        {Object.entries(SUMMARY_LABELS).map(([key, name]) => (
                            <div key={key}>
                                <dt className="font-medium">{name}</dt>
                                <dd dir="auto">{proposal.summaries[key]}</dd>
                            </div>
                        ))}
                    </dl>
                </>
            )}
            {proposal.status === "pending" ? (
                <div className="flex gap-2 mt-3">
                    <button onClick={onApply} disabled={busy}
                        className="px-3 py-1.5 bg-green-700 text-white rounded-lg font-medium hover:bg-green-800 disabled:opacity-60">
                        {relabel ? `Apply ${proposal.changes.length} change${proposal.changes.length === 1 ? "" : "s"}` : "Apply"}
                    </button>
                    <button onClick={onDismiss} disabled={busy}
                        className="px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-60">
                        Dismiss
                    </button>
                </div>
            ) : (
                <p className="mt-3 text-gray-600">{proposal.status === "applied" ? "Applied." : "Dismissed."}</p>
            )}
        </div>
    );
}

Proposal.propTypes = {
    proposal: PropTypes.object.isRequired,
    busy: PropTypes.bool,
    onApply: PropTypes.func.isRequired,
    onDismiss: PropTypes.func.isRequired,
};

// Chat about one finished analysis. The assistant remembers this conversation
// and can propose new summaries or label fixes; nothing changes until Apply.
export default function AnalysisChat({ filename, onUpdate }) {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const endRef = useRef(null);
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    useEffect(() => {
        let current = true;
        authService.getChat(filename)
            .then((history) => current && setMessages(history))
            .catch(() => current && setMessages([]));
        return () => { current = false; };
    }, [filename]);

    useEffect(() => {
        endRef.current?.scrollIntoView?.({ block: "nearest" });
    }, [messages]);

    const send = async (e) => {
        e.preventDefault();
        const text = input.trim();
        if (!text) return;
        setBusy(true);
        setError("");
        setMessages((current) => [...current, { id: `local-${Date.now()}`, role: "user", text }]);
        setInput("");
        try {
            const data = await authService.sendChat(filename, text);
            if (!mounted.current) return;
            setMessages((current) => [
                ...current,
                { id: `reply-${Date.now()}`, role: "model", text: data.reply },
                ...data.proposals.map((p) => ({ ...p, role: "proposal" })),
            ]);
        } catch (err) {
            setError(err.response?.status === 429
                ? "Too many messages. Please wait a minute."
                : errorMessage(err, "The assistant could not answer. Please try again."));
        } finally {
            setBusy(false);
        }
    };

    const decide = async (proposal, apply) => {
        setBusy(true);
        setError("");
        try {
            if (apply) {
                const result = await authService.applyProposal(filename, proposal.id);
                if (!mounted.current) return;  // the user moved on to another result
                onUpdate(result);
            } else {
                await authService.dismissProposal(filename, proposal.id);
            }
            setMessages((current) => current.map((m) =>
                m.id === proposal.id ? { ...m, status: apply ? "applied" : "dismissed" } : m));
        } catch {
            setError("That change could not be saved. Please try again.");
        } finally {
            setBusy(false);
        }
    };

    return (
        <section aria-labelledby="chat-heading" className="w-full max-w-3xl mt-6 bg-white border border-gray-200 rounded-lg shadow-sm p-4">
            <h3 id="chat-heading" className="font-bold text-lg text-gray-900">Ask about these results</h3>
            <p className="text-sm text-gray-600 mb-3">
                Ask questions about the comments, ask for different summaries, or point out mislabelled comments.
                Nothing changes until you press Apply.
            </p>

            <div role="log" aria-live="polite" aria-label="Conversation" className="max-h-96 overflow-y-auto mb-3">
            <ol className="space-y-3">
                {messages.map((m) => (
                    <li key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
                        {m.role === "proposal" ? (
                            <Proposal proposal={m} busy={busy} onApply={() => decide(m, true)} onDismiss={() => decide(m, false)} />
                        ) : (
                            <p dir="auto" className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                                m.role === "user" ? "bg-green-700 text-white" : "bg-gray-100 text-gray-900"}`}>
                                <span className="sr-only">{m.role === "user" ? "You: " : "Assistant: "}</span>
                                {m.text}
                            </p>
                        )}
                    </li>
                ))}
            </ol>
            <div ref={endRef} />
            </div>
            {busy && <p role="status" className="text-sm text-gray-600 mb-2">Thinking…</p>}
            {error && <p role="alert" className="text-sm text-red-700 mb-2">{error}</p>}

            <form onSubmit={send} className="flex flex-col sm:flex-row gap-2">
                <label htmlFor="chat-input" className="sr-only">Your question</label>
                <input
                    id="chat-input"
                    dir="auto"
                    value={input}
                    maxLength={2000}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="e.g. What are people angry about?"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                />
                <button type="submit" disabled={busy || !input.trim()}
                    className="px-4 py-2 bg-green-700 text-white rounded-lg font-medium hover:bg-green-800 disabled:opacity-60">
                    Send
                </button>
            </form>
        </section>
    );
}

AnalysisChat.propTypes = {
    filename: PropTypes.string.isRequired,
    onUpdate: PropTypes.func.isRequired,
};
