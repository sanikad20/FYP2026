import { useState, useEffect, useRef } from "react";
import { Bot, Moon, Sun, FileText, Download, ExternalLink } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { Button } from "@/components/ui/button";
import MessageBubble from "@/components/chat/MessageBubble";
import TypingIndicator from "@/components/chat/TypingIndicator";
import MapPreviewCard from "@/components/chat/MapPreviewCard";
import FacultyCarousel from "@/components/chat/FacultyCarousel";
import PlacementChart from "@/components/chat/PlacementChart";
import ChatInput from "@/components/chat/ChatInput";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { sendMessage, checkHealth, NavigationData } from "@/lib/chatApi";
import { toast } from "sonner";

interface Message {
  id: string;
  type: "text" | "quick-reply" | "map" | "faculty" | "placements" | "pdf" | "navigation";
  content?: string;
  isUser: boolean;
  sourceFile?: string;
  servePdf?: string;
  servePdfPath?: string;
  navigation?: NavigationData;
}

const buildPdfUrl = (filename: string, filepath?: string) => {
  if (!filepath?.trim()) {
    return `http://localhost:5000/docs/${encodeURIComponent(filename)}`;
  }

  // Normalize slashes for Windows paths.
  const normalized = filepath.replace(/\\/g, "/").trim();

  // If backend already sends a web path, use it directly.
  if (normalized.startsWith("/docs/")) {
    return `http://localhost:5000${normalized}`;
  }

  // If backend sends absolute disk path, extract basename and serve via /docs.
  const extractedName = normalized.split("/").pop() || filename;
  return `http://localhost:5000/docs/${encodeURIComponent(extractedName)}`;
};

const buildNavImageUrl = (imageUrl?: string | null, imageName?: string | null) => {
  if (imageUrl && imageUrl.trim()) {
    const normalized = imageUrl.trim();
    if (normalized.startsWith("http://") || normalized.startsWith("https://")) {
      return normalized;
    }
    if (normalized.startsWith("/")) {
      return `http://localhost:5000${normalized}`;
    }
    return `http://localhost:5000/${normalized}`;
  }

  if (imageName && imageName.trim()) {
    return `http://localhost:5000/nav-images/${encodeURIComponent(imageName)}`;
  }

  return "";
};

const PdfAttachmentCard = ({
  filename,
  filepath,
  caption,
}: {
  filename: string;
  filepath: string;
  caption?: string;
}) => {
  const title = filename.replace(/(\.pdf)+$/i, "").replace(/_/g, " ");
  const fileUrl = buildPdfUrl(filename, filepath);

  return (
    <div className="flex max-w-sm flex-col gap-2">
      {caption && <p className="text-sm text-muted-foreground">{caption}</p>}
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-3 shadow-sm">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-500/10">
          <FileText className="h-5 w-5 text-red-500" />
        </div>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">PDF Document</p>
        </div>

        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title="Open PDF"
            onClick={() => window.open(fileUrl, "_blank")}
          >
            <ExternalLink className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title="Download PDF"
            onClick={() => {
              const a = document.createElement("a");
              a.href = fileUrl;
              a.download = filename;
              a.click();
            }}
          >
            <Download className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
};

const NavigationCard = ({
  title,
  navigation,
}: {
  title?: string;
  navigation: NavigationData;
}) => {
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-card p-4 shadow-sm">
        {title && <p className="mb-3 text-sm text-muted-foreground">{title}</p>}

        <div className="space-y-4">
          {navigation.steps.map((step) => {
            const imgSrc = buildNavImageUrl(step.image_url, step.image ?? null);
            return (
              <div key={`${step.step}-${step.location}`} className="rounded-lg border border-border/70 p-3">
                <p className="text-sm font-semibold">
                  Step {step.step}: {step.location}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">{step.instruction}</p>
                {imgSrc ? (
                  <img
                    src={imgSrc}
                    alt={`Step ${step.step} reference`}
                    className="mt-3 w-full rounded-md border border-border object-cover"
                    loading="lazy"
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const Index = () => {
  const { theme, setTheme } = useTheme();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      type: "text",
      content:
        "Hello! I'm your Smart Campus Assistant. I'm here to help you navigate campus, find faculty, check placement stats, and answer your questions.",
      isUser: false,
    },
  ]);
  const [isTyping, setIsTyping] = useState(false);

  useEffect(() => {
    checkHealth().then(setBackendOnline);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

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

      if (response.serve_pdf) {
        setMessages((prev) => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            type: "pdf",
            content: response.reply,
            isUser: false,
            servePdf: response.serve_pdf,
            servePdfPath: response.serve_pdf_path,
          },
        ]);
      } else if (response.navigation) {
        setMessages((prev) => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            type: "navigation",
            content: response.reply,
            isUser: false,
            navigation: response.navigation,
          },
        ]);
      } else {
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
      }
    } catch {
      setIsTyping(false);
      toast.error("Could not reach the backend. Make sure the Python server is running.");
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: "text",
          content:
            "I couldn't connect to the backend server. Please make sure the Python server is running (python backend_api.py).",
          isUser: false,
        },
      ]);
    }
  };

  return (
    <SidebarProvider defaultOpen={true}>
      <div className="flex min-h-screen w-full bg-transparent">
        <AppSidebar />

        <div className="flex flex-1 flex-col">
          <header className="sticky top-0 z-10 border-b border-border/70 bg-card/60 backdrop-blur-md">
            <div className="flex items-center justify-between p-4">
              <div className="flex items-center gap-3">
                <SidebarTrigger />
                <div className="flex items-center gap-2">
                  <Bot className="h-5 w-5 text-primary" />
                  <h1 className="text-lg font-semibold tracking-tight md:text-xl">Smart Campus Assistant</h1>
                  {backendOnline !== null && (
                    <span
                      className={`ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] ${
                        backendOnline ? "bg-green-500/10 text-green-600" : "bg-destructive/10 text-destructive"
                      }`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${backendOnline ? "bg-green-500" : "bg-destructive"}`} />
                      {backendOnline ? "AI ONLINE" : "AI OFFLINE"}
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

          <div className="flex-1 overflow-y-auto">
            <div className="mx-auto max-w-4xl p-4 md:p-6">
              <div className="rounded-2xl border border-border/60 bg-card/55 p-4 shadow-card backdrop-blur-sm md:p-6">
                <div className="space-y-4">
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
                    if (message.type === "map") {
                      return <MapPreviewCard key={message.id} />;
                    }
                    if (message.type === "faculty") {
                      return <FacultyCarousel key={message.id} />;
                    }
                    if (message.type === "placements") {
                      return <PlacementChart key={message.id} />;
                    }
                    if (message.type === "navigation" && message.navigation) {
                      return (
                        <NavigationCard
                          key={message.id}
                          title={message.content}
                          navigation={message.navigation}
                        />
                      );
                    }
                    if (message.type === "pdf" && message.servePdf) {
                      return (
                        <div key={message.id} className="flex justify-start">
                          <div className="flex max-w-sm flex-col gap-2">
                            <PdfAttachmentCard
                              filename={message.servePdf}
                              filepath={message.servePdfPath ?? ""}
                              caption={message.content}
                            />
                          </div>
                        </div>
                      );
                    }
                    return null;
                  })}
                  {isTyping && <TypingIndicator />}
                  <div ref={messagesEndRef} />
                </div>
              </div>
            </div>
          </div>

          <div className="sticky bottom-0 border-t border-border/70 bg-card/60 backdrop-blur-md">
            <div className="mx-auto max-w-4xl p-4">
              <ChatInput onSend={handleSendMessage} disabled={isTyping} />
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default Index;