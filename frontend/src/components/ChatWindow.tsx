import { FormEvent, useEffect, useRef, useState } from "react";
import { SendHorizonal } from "lucide-react";
import AgentThinking from "./AgentThinking";
import MessageBubble, { Message } from "./MessageBubble";

const samplePrompts = [
  "Summarize account health for Acme Corp",
  "Which deals are at risk this quarter?",
  "Draft a follow-up for the TechCo contact",
  "Show me the pipeline summary"
];

const threadId = crypto.randomUUID();

type AgentPayload = {
  response: string;
  tools_used: string[];
  trace?: Record<string, unknown>;
  evaluation?: Record<string, unknown>;
};

type Props = {
  onAgentResponse?: (payload: AgentPayload) => void;
};

export default function ChatWindow({ onAgentResponse }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  async function sendMessage(nextMessage?: string) {
    const text = (nextMessage ?? input).trim();
    if (!text || isThinking) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text
    };
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setIsThinking(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, thread_id: threadId })
      });
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }
      const payload: AgentPayload = await response.json();
      onAgentResponse?.(payload);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "agent",
          content: payload.response,
          toolsUsed: payload.tools_used
        }
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "agent",
          content:
            error instanceof Error
              ? `I could not reach AgentDesk API. ${error.message}`
              : "I could not reach AgentDesk API.",
          toolsUsed: []
        }
      ]);
    } finally {
      setIsThinking(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage();
  }

  return (
    <section className="flex h-full min-h-0 flex-1 flex-col bg-slate-100">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-electric-500">
            Agentforce-style CRM Agent
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">AgentDesk</h1>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
        {messages.length === 0 ? (
          <div className="mx-auto flex h-full max-w-3xl flex-col justify-center">
            <div className="mb-7">
              <h2 className="text-3xl font-semibold text-slate-950">Ask your CRM what to do next.</h2>
              <p className="mt-3 max-w-2xl text-base leading-7 text-slate-600">
                Query accounts, inspect pipeline risk, draft follow-ups, and create tasks from one workspace.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {samplePrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => void sendMessage(prompt)}
                  className="rounded-lg border border-slate-200 bg-white p-4 text-left text-sm font-medium leading-6 text-slate-700 shadow-sm transition hover:border-electric-400 hover:text-navy-900"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-5">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {isThinking && (
              <div className="flex justify-start">
                <AgentThinking />
              </div>
            )}
            <div ref={scrollRef} />
          </div>
        )}
      </div>

      <footer className="border-t border-slate-200 bg-white px-4 py-4 sm:px-8">
        <form onSubmit={onSubmit} className="mx-auto flex max-w-4xl gap-3">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about accounts, deals, follow-ups, or tasks..."
            className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-electric-500 focus:ring-4 focus:ring-electric-500/15"
          />
          <button
            type="submit"
            disabled={isThinking || input.trim().length === 0}
            className="inline-flex h-12 w-12 flex-none items-center justify-center rounded-lg bg-electric-500 text-white shadow-soft transition hover:bg-electric-400 disabled:cursor-not-allowed disabled:bg-slate-300"
            title="Send"
            aria-label="Send"
          >
            <SendHorizonal size={19} />
          </button>
        </form>
      </footer>
    </section>
  );
}
