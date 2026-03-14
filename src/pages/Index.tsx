import { useState, useEffect, useRef } from "react";
import { Bot, Moon, Sun, AlertCircle } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { Button } from "@/components/ui/button";
import MessageBubble from "@/components/chat/MessageBubble";
import TypingIndicator from "@/components/chat/TypingIndicator";
import QuickReplyButtons from "@/components/chat/QuickReplyButtons";
import MapPreviewCard from "@/components/chat/MapPreviewCard";
import FacultyCarousel from "@/components/chat/FacultyCarousel";
import PlacementChart from "@/components/chat/PlacementChart";
import ChatInput from "@/components/chat/ChatInput";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { sendMessage, checkHealth } from "@/lib/chatApi";
import { toast } from "sonner";

interface Message {
  id: string;
  type: "text" | "quick-reply" | "map" | "faculty" | "placements";
  content?: string;
  isUser: boolean;
  sourceFile?: string;
}

const Index = () => {
  const { theme, setTheme } = useTheme();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
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

  // Check backend health on mount
  useEffect(() => {
    checkHealth().then(setBackendOnline);
  }, []);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleQuickReply = (action: string) => {
    if (action === "map" || action === "faculty" || action === "placements") {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          type: "text",
          content: `Show me ${action === "map" ? "campus map" : action === "faculty" ? "faculty list" : "placement statistics"}`,
          isUser: true,
        },
      ]);
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
      }, 500);
      return;
    }
  };

  const handleSendMessage = async (content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        type: "text",
        content,
        isUser: true,
      },
    ]);

    setIsTyping(true);

    try {
      const response = await sendMessage(content);
      setIsTyping(false);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: "text",
          content: response.reply,
          isUser: false,
          sourceFile: response.source_file,
        },
      ]);
    } catch (error) {
      setIsTyping(false);
      toast.error("Could not reach the backend. Make sure the Python server is running.");
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: "text",
          content: "⚠️ I couldn't connect to the backend server. Please make sure the Python server is running (`python backend_api.py`).",
          isUser: false,
        },
      ]);
    }
  };

  return (
    <SidebarProvider defaultOpen={true}>
      <div className="min-h-screen w-full flex bg-background">
        <AppSidebar />
        
        <div className="flex-1 flex flex-col">
          {/* Header */}
          <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
            <div className="flex items-center justify-between p-4">
              <div className="flex items-center gap-3">
                <SidebarTrigger />
                <div className="flex items-center gap-2">
                  <Bot className="h-5 w-5 text-primary" />
                  <h1 className="text-lg font-semibold">Smart Campus Assistant</h1>
                  {backendOnline !== null && (
                    <span className={`ml-2 inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${backendOnline ? 'bg-green-500/10 text-green-600' : 'bg-destructive/10 text-destructive'}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${backendOnline ? 'bg-green-500' : 'bg-destructive'}`} />
                      {backendOnline ? 'AI Online' : 'AI Offline'}
                    </span>
                  )}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                className="h-9 w-9 rounded-lg"
              >
                <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
                <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
                <span className="sr-only">Toggle theme</span>
              </Button>
            </div>
          </header>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto p-6 space-y-4">
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
          </div>

          {/* Input */}
          <div className="border-t border-border bg-card/50 backdrop-blur-sm sticky bottom-0">
            <div className="max-w-3xl mx-auto p-4">
              <ChatInput onSend={handleSendMessage} disabled={isTyping} />
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default Index;
