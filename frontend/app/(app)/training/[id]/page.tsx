"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Markdown } from "@/components/markdown";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorState, Loading, PageHeader, TLink } from "@/components/ui";
import { api, download } from "@/lib/api";

type Enrollment = { id: string; module_id: string; module_title: string; status: string; completed_lessons: string[]; progress_pct: number };
type Module = {
  id: string;
  title: string;
  description: string;
  lessons: { id: string; title: string; content_md: string }[];
  quiz: { id: string; pass_mark: number; questions: { id: string; prompt: string; options: string[] }[] } | null;
};
type QuizResult = { score: number; passed: boolean; pass_mark: number; certificate_id: string | null; feedback: { question_id: string; correct: boolean; correct_index: number; explanation: string }[] };

export default function ModulePlayer() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const [lessonIdx, setLessonIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [result, setResult] = useState<QuizResult | null>(null);

  const enrollment = useQuery({
    queryKey: ["my-training"],
    queryFn: () => api<Enrollment[]>("/training/my"),
    select: (all) => all.find((e) => e.id === id),
  });
  const mod = useQuery({
    queryKey: ["module", enrollment.data?.module_id],
    queryFn: () => api<Module>(`/training/modules/${enrollment.data!.module_id}`),
    enabled: !!enrollment.data,
  });

  if (enrollment.isLoading || mod.isLoading) return <Loading />;
  if (!enrollment.data) return <ErrorState error={new Error("Enrollment not found")} />;
  if (mod.error) return <ErrorState error={mod.error} />;
  const e = enrollment.data;
  const m = mod.data!;
  const lesson = m.lessons[lessonIdx];
  const lessonsDone = m.lessons.every((l) => e.completed_lessons.includes(l.id));

  const completeLesson = async () => {
    try {
      await api(`/training/enrollments/${id}/lessons/${lesson.id}/complete`, { method: "POST" });
      await qc.invalidateQueries({ queryKey: ["my-training"] });
      if (lessonIdx < m.lessons.length - 1) setLessonIdx(lessonIdx + 1);
    } catch (err) {
      toast.error(err);
    }
  };

  const submitQuiz = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!m.quiz) return;
    try {
      const r = await api<QuizResult>(`/training/enrollments/${id}/quiz`, {
        method: "POST",
        body: { answers: m.quiz.questions.map((q) => answers[q.id] ?? -1) },
      });
      setResult(r);
      qc.invalidateQueries({ queryKey: ["my-training"] });
      qc.invalidateQueries({ queryKey: ["certs"] });
      qc.invalidateQueries({ queryKey: ["badges"] });
    } catch (err) {
      toast.error(err);
    }
  };

  return (
    <>
      <PageHeader title={m.title} subtitle={<>{m.description} · <Badge>{e.progress_pct}% complete</Badge></>} actions={<TLink href="/training">Back to training</TLink>} />
      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <nav aria-label="Lessons">
          <ol className="space-y-1">
            {m.lessons.map((l, i) => (
              <li key={l.id}>
                <button
                  onClick={() => setLessonIdx(i)}
                  aria-current={i === lessonIdx ? "step" : undefined}
                  className={"w-full rounded px-2 py-1 text-left text-sm " + (i === lessonIdx ? "bg-blue-700 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800")}
                >
                  {e.completed_lessons.includes(l.id) ? "✓ " : `${i + 1}. `}{l.title}
                </button>
              </li>
            ))}
            <li className="px-2 py-1 text-sm font-semibold">Quiz {lessonsDone ? "" : "(finish lessons first)"}</li>
          </ol>
        </nav>
        <div className="space-y-4">
          {lesson && (
            <Card title={lesson.title}>
              <Markdown text={lesson.content_md} />
              <Button className="mt-4" onClick={completeLesson} disabled={e.completed_lessons.includes(lesson.id) && lessonIdx === m.lessons.length - 1}>
                {e.completed_lessons.includes(lesson.id) ? "Completed ✓ — next" : "Mark lesson complete"}
              </Button>
            </Card>
          )}
          {m.quiz && lessonsDone && (
            <Card title={`Quiz (pass mark ${m.quiz.pass_mark}%)`}>
              <form onSubmit={submitQuiz} className="space-y-4">
                {m.quiz.questions.map((q, qi) => {
                  const fb = result?.feedback.find((f) => f.question_id === q.id);
                  return (
                    <fieldset key={q.id} className="rounded border border-slate-200 p-3 dark:border-slate-700">
                      <legend className="px-1 text-sm font-semibold">{qi + 1}. {q.prompt}</legend>
                      {q.options.map((o, oi) => (
                        <label key={oi} className="flex items-center gap-2 py-1 text-sm">
                          <input type="radio" name={q.id} checked={answers[q.id] === oi} onChange={() => setAnswers({ ...answers, [q.id]: oi })} required />
                          {o}
                        </label>
                      ))}
                      {fb && (
                        <p className={"mt-1 text-sm " + (fb.correct ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400")}>
                          {fb.correct ? "Correct. " : `Not quite — the answer is “${q.options[fb.correct_index]}”. `}
                          {fb.explanation}
                        </p>
                      )}
                    </fieldset>
                  );
                })}
                <Button type="submit">Submit answers</Button>
              </form>
              {result && (
                <div role="status" className="mt-4 rounded bg-slate-100 p-3 text-sm dark:bg-slate-800">
                  Score: <b>{result.score}%</b> — {result.passed ? "Passed 🎉" : `Not passed (need ${result.pass_mark}%). Review and try again.`}
                  {result.certificate_id && (
                    <Button variant="secondary" className="ml-3" onClick={() => download(`/training/certificates/${result.certificate_id}/pdf`, "certificate.pdf").catch(toast.error)}>
                      Download certificate
                    </Button>
                  )}
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
