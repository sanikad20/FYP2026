const TypingIndicator = () => {
  return (
    <div className="flex w-full justify-start animate-bubble-in">
      <div className="max-w-[86%] rounded-2xl rounded-bl-md border border-border/70 bg-chat-bot-bg px-4 py-3 shadow-card">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/20">
            <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
          </div>

          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold tracking-wide">Assistant is generating a response</p>
            <div className="mt-1 h-1.5 w-40 overflow-hidden rounded-full bg-muted">
              <div className="h-full w-full animate-typing-shimmer bg-gradient-to-r from-transparent via-primary/40 to-transparent bg-[length:200%_100%]" />
            </div>
          </div>

          <div className="flex items-end gap-1">
            <span className="h-3 w-1 rounded-full bg-primary/60 animate-typing-bar [animation-delay:0ms]" />
            <span className="h-4 w-1 rounded-full bg-primary/80 animate-typing-bar [animation-delay:120ms]" />
            <span className="h-5 w-1 rounded-full bg-primary animate-typing-bar [animation-delay:240ms]" />
          </div>
        </div>
      </div>
    </div>
  );
};

export default TypingIndicator;