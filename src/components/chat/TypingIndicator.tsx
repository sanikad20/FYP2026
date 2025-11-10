const TypingIndicator = () => {
  return (
    <div className="flex w-full justify-start animate-fade-in-up">
      <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-chat-bot-bg text-chat-bot-fg border border-border px-4 py-3 shadow-sm">
        <div className="flex items-center space-x-2">
          <div className="flex space-x-1">
            <div
              className="h-2 w-2 rounded-full bg-primary/60 animate-bounce-dots"
              style={{ animationDelay: "0s" }}
            />
            <div
              className="h-2 w-2 rounded-full bg-primary/60 animate-bounce-dots"
              style={{ animationDelay: "0.2s" }}
            />
            <div
              className="h-2 w-2 rounded-full bg-primary/60 animate-bounce-dots"
              style={{ animationDelay: "0.4s" }}
            />
          </div>
          <span className="text-xs text-muted-foreground">Bot is typing...</span>
        </div>
      </div>
    </div>
  );
};

export default TypingIndicator;
