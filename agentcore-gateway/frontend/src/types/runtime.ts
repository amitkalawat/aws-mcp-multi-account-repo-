export interface RuntimeRequest {
  prompt: string;
}

export interface RuntimeResponse {
  response: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}
