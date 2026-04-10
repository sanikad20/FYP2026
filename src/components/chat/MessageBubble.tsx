import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  message: string;
  isUser: boolean;
  timestamp?: string;
}

const MessageBubble = ({ message, isUser, timestamp }: MessageBubbleProps) => {
  return (
    <div className={cn("flex w-full animate-bubble-in", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[88%] md:max-w-[74%] xl:max-w-[68%] rounded-2xl px-4 py-3.5 shadow-card",
          isUser
            ? "bg-chat-user-bg text-chat-user-fg rounded-br-md"
            : "bg-chat-bot-bg text-chat-bot-fg border border-border rounded-bl-md"
        )}
      >
        <p className="text-sm md:text-[0.95rem] leading-7">{message}</p>
        {timestamp && <p className="mt-1 text-xs opacity-60">{timestamp}</p>}
      </div>
    </div>
  );
};

export default MessageBubble;