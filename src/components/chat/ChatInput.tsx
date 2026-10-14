import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Mic, MicOff, Send } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

const ChatInput = ({ onSend, disabled }: ChatInputProps) => {
  const [message, setMessage] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
    };
  }, []);

  const stopVoiceInput = () => {
    recognitionRef.current?.stop();
    setIsListening(false);
  };

  const handleSend = () => {
    if (message.trim() && !disabled) {
      onSend(message);
      setMessage("");
      stopVoiceInput();
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const startVoiceInput = () => {
    if (disabled || isListening) {
      stopVoiceInput();
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setVoiceError("Speech recognition is not supported in this browser.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setVoiceError("");
      setIsListening(true);
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let transcript = "";
      for (let index = 0; index < event.results.length; index += 1) {
        transcript += event.results[index][0].transcript;
      }
      setMessage(transcript.trim());
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === "not-allowed") {
        setVoiceError("Microphone access was denied. Please allow access and try again.");
      } else if (event.error === "no-speech") {
        setVoiceError("No speech was detected. Please try again.");
      } else {
        setVoiceError("Voice input could not be processed. Please try typing instead.");
      }
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
  };

  return (
    <div className="rounded-2xl border border-border/70 bg-card/80 p-3 shadow-card backdrop-blur supports-[backdrop-filter]:bg-card/60">
      <div className="mb-2 flex min-h-5 items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{voiceError || (isListening ? "Listening..." : "Use voice or type your question")}</span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant={isListening ? "destructive" : "outline"}
          size="icon"
          onClick={startVoiceInput}
          disabled={disabled}
          aria-label={isListening ? "Stop voice input" : "Start voice input"}
          className="h-11 w-11 rounded-xl"
          title={isListening ? "Stop recording" : "Use microphone"}
        >
          {isListening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </Button>
        <Input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyPress}
          placeholder="Type your question..."
          disabled={disabled}
          className="h-11 flex-1 border-border bg-muted/60 text-sm md:text-base placeholder:text-muted-foreground/80 focus-visible:ring-2 focus-visible:ring-primary"
        />
        <Button
          onClick={handleSend}
          disabled={disabled || !message.trim()}
          size="icon"
          className="h-11 w-11 rounded-xl bg-primary text-primary-foreground transition-transform duration-150 hover:scale-[1.03] hover:bg-primary/90 active:scale-95"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
};

export default ChatInput;