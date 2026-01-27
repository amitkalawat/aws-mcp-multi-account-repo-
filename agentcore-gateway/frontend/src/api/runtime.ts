import { RUNTIME_URL } from '../config/amplify';
import type { RuntimeRequest, RuntimeResponse } from '../types/runtime';

// Generate a unique session ID for the browser session (min 33 chars required)
const SESSION_ID = `session-${Date.now()}-${crypto.randomUUID()}`;

export async function sendPrompt(
  prompt: string,
  idToken: string
): Promise<string> {
  const request: RuntimeRequest = { prompt };

  const response = await fetch(RUNTIME_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${idToken}`,
      'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': SESSION_ID,
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Runtime request failed: ${response.status} - ${errorText}`);
  }

  const data: RuntimeResponse = await response.json();
  return data.response;
}

export interface StreamChunk {
  type: 'text' | 'tool_call' | 'tool_result' | 'error' | 'done';
  content?: string;
  name?: string;
  input?: Record<string, unknown>;
  result?: string;
}

export async function sendPromptStreaming(
  prompt: string,
  idToken: string,
  onChunk: (chunk: StreamChunk) => void
): Promise<void> {
  const request: RuntimeRequest = { prompt };

  const response = await fetch(RUNTIME_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${idToken}`,
      'Accept': 'text/event-stream',
      'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': SESSION_ID,
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Runtime request failed: ${response.status} - ${errorText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Try to parse complete JSON objects from buffer
      // The runtime may send multiple JSON objects in sequence
      let startIndex = 0;
      let braceCount = 0;
      let inString = false;
      let escapeNext = false;

      for (let i = 0; i < buffer.length; i++) {
        const char = buffer[i];

        if (escapeNext) {
          escapeNext = false;
          continue;
        }

        if (char === '\\' && inString) {
          escapeNext = true;
          continue;
        }

        if (char === '"' && !escapeNext) {
          inString = !inString;
          continue;
        }

        if (inString) continue;

        if (char === '{') {
          if (braceCount === 0) startIndex = i;
          braceCount++;
        } else if (char === '}') {
          braceCount--;
          if (braceCount === 0) {
            // Found complete JSON object
            const jsonStr = buffer.substring(startIndex, i + 1);
            try {
              const chunk = JSON.parse(jsonStr) as StreamChunk;
              onChunk(chunk);
            } catch {
              // If parsing fails, might be incomplete - keep in buffer
              console.warn('Failed to parse chunk:', jsonStr);
            }
            buffer = buffer.substring(i + 1);
            i = -1; // Reset loop
          }
        }
      }
    }

    // Handle any remaining content (non-streaming response fallback)
    if (buffer.trim()) {
      try {
        const data = JSON.parse(buffer);
        if (data.response) {
          // Non-streaming response format
          onChunk({ type: 'text', content: data.response });
          onChunk({ type: 'done' });
        }
      } catch {
        console.warn('Unparsed buffer content:', buffer);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
