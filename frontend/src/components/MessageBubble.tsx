import { marked } from "marked";

export type Message = {
  id: string;
  role: "user" | "agent";
  content: string;
  toolsUsed?: string[];
};

type Props = {
  message: Message;
};

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const html = isUser ? "" : marked.parse(message.content, { async: false });

  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[82%] ${isUser ? "text-right" : "text-left"}`}>
        <div
          className={
            isUser
              ? "rounded-lg bg-electric-500 px-4 py-3 text-sm leading-6 text-white shadow-soft"
              : "prose prose-sm max-w-none rounded-lg bg-white px-4 py-3 leading-6 text-slate-800 shadow-soft prose-p:my-2 prose-ul:my-2 prose-li:my-1"
          }
        >
          {isUser ? (
            message.content
          ) : (
            <div dangerouslySetInnerHTML={{ __html: html }} />
          )}
        </div>
        {!isUser && message.toolsUsed && message.toolsUsed.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.toolsUsed.map((tool) => (
              <span
                key={tool}
                className="rounded-full border border-electric-300/60 bg-electric-300/15 px-2.5 py-1 text-xs font-semibold text-electric-300"
              >
                🔧 {tool}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
