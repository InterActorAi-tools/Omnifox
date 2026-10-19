import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import AnalysisChat from "../components/AnalysisChat";
import { authService } from "../services/authService";

const summaries = { overall: "New overall", positive: "P", neutral: "N", negative: "X" };

describe("AnalysisChat", () => {
    it("sends a question, shows the answer and applies a proposal only on request", async () => {
        vi.spyOn(authService, "getChat").mockResolvedValue([]);
        vi.spyOn(authService, "sendChat").mockResolvedValue({
            reply: "Here are new summaries.",
            proposals: [{ id: 7, type: "summaries", summaries, status: "pending" }],
        });
        const result = { overall_summary: "New overall" };
        const apply = vi.spyOn(authService, "applyProposal").mockResolvedValue(result);
        const onUpdate = vi.fn();
        render(<AnalysisChat filename="processed_a.xlsx" onUpdate={onUpdate} />);

        fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Focus on prices" } });
        fireEvent.click(screen.getByRole("button", { name: "Send" }));

        expect(await screen.findByText("Here are new summaries.")).toBeInTheDocument();
        expect(screen.getByText("New overall")).toBeInTheDocument();
        expect(authService.sendChat).toHaveBeenCalledWith("processed_a.xlsx", "Focus on prices");
        expect(onUpdate).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole("button", { name: "Apply" }));
        expect(await screen.findByText("Applied.")).toBeInTheDocument();
        expect(apply).toHaveBeenCalledWith("processed_a.xlsx", 7);
        expect(onUpdate).toHaveBeenCalledWith(result);
    });
});

describe("AnalysisChat relabel proposals", () => {
    it("lists each change before it is applied", async () => {
        vi.spyOn(authService, "getChat").mockResolvedValue([{
            id: 3, role: "proposal", type: "relabel", status: "pending", reason: "Sarcasm",
            changes: [{ id: 1, translation: "great work", from: { sentiment: "positive", category: "Governance" },
                to: { sentiment: "negative", category: "Governance" } }],
        }]);
        render(<AnalysisChat filename="processed_a.xlsx" onUpdate={vi.fn()} />);

        expect(await screen.findByText("Proposed label changes (1)")).toBeInTheDocument();
        expect(screen.getByText("negative · Governance")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Apply 1 change" })).toBeInTheDocument();
    });
});
