const API_BASE_URL = "http://localhost:5000";

let sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;

export function resetSession() {
  sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

export interface ChatResponse {
  reply: string;
  source_file?: string;
  // PDF serve fields — present when backend returns a document directly
  serve_pdf?: string;
  serve_pdf_path?: string;
}

export async function sendMessage(message: string): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });

  if (!response.ok) {
    throw new Error(`Server error: ${response.status}`);
  }

  return response.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    return response.ok;
  } catch {
    return false;
  }
}