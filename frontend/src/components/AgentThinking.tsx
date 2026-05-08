export default function AgentThinking() {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white px-4 py-3 text-sm font-medium text-slate-600 shadow-soft">
      <span>AgentDesk is thinking</span>
      <span className="flex gap-1" aria-hidden="true">
        <span className="dot h-1.5 w-1.5 rounded-full bg-electric-500" />
        <span className="dot h-1.5 w-1.5 rounded-full bg-electric-500" />
        <span className="dot h-1.5 w-1.5 rounded-full bg-electric-500" />
      </span>
    </div>
  );
}
