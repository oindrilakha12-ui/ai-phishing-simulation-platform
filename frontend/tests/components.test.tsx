import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IndicatorList, ScoreGauge } from "@/components/indicators";
import { Markdown } from "@/components/markdown";
import { PreviewSandbox } from "@/components/preview-sandbox";
import { Badge, DemoBadge, ErrorState, Pagination, Tabs } from "@/components/ui";
import { ApiError, qs } from "@/lib/api";
import { atLeast, pct } from "@/lib/format";
import type { Preview } from "@/lib/types";

const preview: Preview = {
  template_id: "t1",
  document: '<!doctype html><html><body><div>SIMULATION — TRAINING ONLY</div><p>Dear <mark data-flag="f1">employee</mark></p></body></html>',
  red_flags: [{ id: "f1", category: "greeting", description: "Generic greeting", cue: "employee" }],
  links: [{ index: 0, href: "http://evil.example/x", text: "intranet.globex.example", actual_host: "evil.example", displayed_host: "intranet.globex.example", mismatch: true }],
  landing_page: "<!doctype html><p>This was a training simulation</p>",
  watermark: "SIMULATION — TRAINING ONLY",
};

describe("PreviewSandbox", () => {
  it("renders the lure in a script-less sandboxed iframe", () => {
    render(<PreviewSandbox preview={preview} />);
    const frame = screen.getByTitle("Sandboxed email preview") as HTMLIFrameElement;
    const sandbox = frame.getAttribute("sandbox") ?? "";
    expect(sandbox).toBe("allow-same-origin");
    expect(sandbox).not.toContain("allow-scripts");
    expect(sandbox).not.toContain("allow-forms");
    expect(sandbox).not.toContain("allow-top-navigation");
    expect(frame.getAttribute("srcdoc")).toContain("SIMULATION — TRAINING ONLY");
  });

  it("shows red flags and the inspect-link mismatch", () => {
    render(<PreviewSandbox preview={preview} />);
    expect(screen.getByText("Generic greeting")).toBeInTheDocument();
    expect(screen.getByText(/Mismatch: shows intranet.globex.example, goes to evil.example/)).toBeInTheDocument();
    const flagButton = screen.getByRole("button", { name: /Greeting/ });
    fireEvent.mouseEnter(flagButton);
    expect(flagButton).toHaveAttribute("aria-pressed", "true");
  });

  it("toggles to the static educational landing page", () => {
    render(<PreviewSandbox preview={preview} />);
    fireEvent.click(screen.getByRole("button", { name: /educational landing page/ }));
    const frame = screen.getByTitle(/Educational landing page/) as HTMLIFrameElement;
    expect(frame.getAttribute("srcdoc")).not.toMatch(/<input|<form/i);
  });

  it("hides the answer key for learners until they act", () => {
    render(<PreviewSandbox preview={{ ...preview, red_flags: [], red_flags_hidden: true }} />);
    expect(screen.getByText(/red flags are revealed afterwards/)).toBeInTheDocument();
  });
});

describe("Markdown", () => {
  it("never injects raw HTML", () => {
    const { container } = render(<Markdown text={'Hello <script>alert(1)</script> **bold** `code`'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });

  it("renders lists", () => {
    const { container } = render(<Markdown text={"1. one\n2. two"} />);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
  });
});

describe("UI primitives", () => {
  it("DemoBadge is labelled and can be hidden", () => {
    const { rerender } = render(<DemoBadge />);
    expect(screen.getByRole("status")).toHaveTextContent("DEMO MODE");
    rerender(<DemoBadge show={false} />);
    expect(screen.queryByText("DEMO MODE")).toBeNull();
  });

  it("ErrorState shows message and request id", () => {
    render(<ErrorState error={new ApiError(404, "not_found", "Campaign not found", undefined, "req-123")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Campaign not found");
    expect(screen.getByRole("alert")).toHaveTextContent("req-123");
  });

  it("Pagination disables buttons at the ends", () => {
    render(<Pagination page={1} pageSize={10} total={25} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByText(/page 1 of 3/)).toBeInTheDocument();
  });

  it("Tabs support arrow-key navigation", () => {
    let value = "a";
    const onChange = (v: string) => (value = v);
    render(<Tabs label="t" value="a" onChange={onChange} tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]} />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "A" }), { key: "ArrowRight" });
    expect(value).toBe("b");
  });

  it("Badge renders text", () => {
    render(<Badge tone="red">high</Badge>);
    expect(screen.getByText("high")).toBeInTheDocument();
  });
});

describe("Indicators", () => {
  it("lists indicators with severity and evidence", () => {
    render(<IndicatorList indicators={[{ id: "x", title: "Lookalike sender domain", severity: "high", explanation: "imitates", evidence: "paypa1.com", category: "sender" }]} />);
    expect(screen.getByText("Lookalike sender domain")).toBeInTheDocument();
    expect(screen.getByText("paypa1.com")).toBeInTheDocument();
  });

  it("score gauge exposes an accessible meter", () => {
    render(<ScoreGauge score={70} label="Score" />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "70");
  });
});

describe("lib helpers", () => {
  it("qs drops empty values", () => {
    expect(qs({ a: 1, b: "", c: undefined, d: "x y" })).toBe("?a=1&d=x+y");
  });
  it("pct and role ranks", () => {
    expect(pct(0.1234)).toBe("12.3%");
    expect(pct(null)).toBe("—");
    expect(atLeast("manager", "learner")).toBe(true);
    expect(atLeast("learner", "manager")).toBe(false);
  });
});
