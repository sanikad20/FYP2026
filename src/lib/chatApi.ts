const API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:5000`;

let sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;

export interface AuthenticatedUser {
  id: number;
  username: string;
  role: string;
  email: string | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const body: { message?: string; error?: string } = await response.json();
    return body.message || body.error || `Server error: ${response.status}`;
  } catch {
    return `Server error: ${response.status}`;
  }
}

export function resetSession() {
  sessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

export async function getCurrentUser(): Promise<AuthenticatedUser | null> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }

  const body: { authenticated: boolean; user: AuthenticatedUser | null } = await response.json();
  return body.authenticated ? body.user : null;
}

export async function login(username: string, password: string): Promise<AuthenticatedUser> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }

  const body: { user: AuthenticatedUser } = await response.json();
  return body.user;
}

export async function register(
  username: string,
  password: string,
  email?: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, email, role: "student" }),
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }
}

export interface NavigationStep {
  step: number;
  node_id?: string;
  location: string;
  instruction: string;
  image?: string | null;
  image_url?: string | null;
  floor: string | number;
}

export interface NavigationData {
  steps: NavigationStep[];
  total_steps: number;
  via_quad: boolean;
  floors_involved: number[];
}

export interface ChatResponse {
  reply: string;
  source_file?: string;
  // PDF serve fields — present when backend returns a document directly
  serve_pdf?: string;
  serve_pdf_path?: string;
  // Navigation payload — present when backend returns route steps
  navigation?: NavigationData;
}

export async function sendMessage(message: string): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
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