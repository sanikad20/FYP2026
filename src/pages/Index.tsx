import { useState, useEffect, useRef } from "react";
import { Bot, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import MessageBubble from "@/components/chat/MessageBubble";
import TypingIndicator from "@/components/chat/TypingIndicator";
import QuickReplyButtons from "@/components/chat/QuickReplyButtons";
import MapPreviewCard from "@/components/chat/MapPreviewCard";
import FacultyCarousel from "@/components/chat/FacultyCarousel";
import PlacementChart from "@/components/chat/PlacementChart";
import ChatInput from "@/components/chat/ChatInput";

interface Message {
  id: string;
  type: "text" | "quick-reply" | "map" | "faculty" | "placements";
  content?: string;
  isUser: boolean;
}

const Index = () => {
  const { theme, setTheme } = useTheme();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      type: "text",
      content: "👋 Hello! I'm your Smart Campus Assistant. I'm here to help you navigate campus, find faculty, check placement stats, and answer all your questions!",
      isUser: false,
    },
    {
      id: "2",
      type: "quick-reply",
      isUser: false,
    },
  ]);
  const [isTyping, setIsTyping] = useState(false);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleQuickReply = (action: string) => {
    // Add user message
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        type: "text",
        content: `Show me ${action === "map" ? "campus map" : action === "faculty" ? "faculty list" : "placement statistics"}`,
        isUser: true,
      },
    ]);

    // Simulate bot typing
    setIsTyping(true);
    setTimeout(() => {
      setIsTyping(false);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: action as "map" | "faculty" | "placements",
          isUser: false,
        },
      ]);
    }, 1500);
  };

  const handleSendMessage = (content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        type: "text",
        content,
        isUser: true,
      },
    ]);

    // Simulate bot response
    setIsTyping(true);
    setTimeout(() => {
      setIsTyping(false);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: "text",
          content: "I understand you're looking for information. How can I help you with that?",
          isUser: false,
        },
      ]);
    }, 1500);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-primary-light/10 to-background p-4">
      <div className="w-full max-w-3xl h-[90vh] rounded-3xl shadow-elevated bg-card border border-border overflow-hidden flex flex-col">
        {/* Header */}
        <div className="bg-gradient-to-r from-primary to-primary/90 p-6 text-primary-foreground">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-12 w-12 rounded-full bg-primary-foreground/10 flex items-center justify-center">
                <Bot className="h-6 w-6" />
              </div>
              <div>
                <h1 className="text-xl font-bold">Smart Campus Assistant</h1>
                <p className="text-sm opacity-90">Always here to help</p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              className="h-10 w-10 rounded-full bg-primary-foreground/10 hover:bg-primary-foreground/20 text-primary-foreground"
            >
              <Sun className="h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
              <Moon className="absolute h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
              <span className="sr-only">Toggle theme</span>
            </Button>
          </div>
        </div>

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.map((message) => {
            if (message.type === "text") {
              return (
                <MessageBubble
                  key={message.id}
                  message={message.content || ""}
                  isUser={message.isUser}
                />
              );
            }
            if (message.type === "quick-reply") {
              return (
                <QuickReplyButtons
                  key={message.id}
                  onSelect={handleQuickReply}
                />
              );
            }
            if (message.type === "map") {
              return <MapPreviewCard key={message.id} />;
            }
            if (message.type === "faculty") {
              return <FacultyCarousel key={message.id} />;
            }
            if (message.type === "placements") {
              return <PlacementChart key={message.id} />;
            }
            return null;
          })}
          {isTyping && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <ChatInput onSend={handleSendMessage} disabled={isTyping} />
      </div>
    </div>
  );
};

export default Index;
