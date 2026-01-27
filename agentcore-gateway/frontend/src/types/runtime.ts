export interface RuntimeRequest {
  prompt: string;
  access_token: string;
}

export interface RuntimeResponse {
  response?: string;
  error?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}
