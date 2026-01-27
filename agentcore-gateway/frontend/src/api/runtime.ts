import { RUNTIME_URL } from '../config/amplify';

// Generate a unique session ID for the browser session (min 33 chars required)
const SESSION_ID = `session-${Date.now()}-${crypto.randomUUID()}`;

export interface ApiResponse {
  response?: string;
  error?: string;
}

// Non-streaming version (kept for fallback)
export async function sendPrompt(
  prompt: string,
  idToken: string
): Promise<ApiResponse> {
  const requestBody = { prompt, access_token: idToken };

  const response = await fetch(RUNTIME_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${idToken}`,
      'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': SESSION_ID,
    },
    body: JSON.stringify(requestBody),
  });

  const text = await response.text();
  if (!response.ok) {
    return { error: `Request failed: ${response.status} - ${text}` };
  }

  try {
    return JSON.parse(text);
  } catch {
    return { error: `Failed to parse response: ${text}` };
  }
}

// Streaming version - calls onText callback as content arrives
export async function sendPromptStreaming(
  prompt: string,
  idToken: string,
  onText: (text: string) => void,
  onError: (error: string) => void,
  onDone: () => void
): Promise<void> {
  console.log('Sending streaming prompt...');

  const requestBody = { prompt, access_token: idToken };

  try {
    const response = await fetch(RUNTIME_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${idToken}`,
        'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': SESSION_ID,
      },
      body: JSON.stringify(requestBody),
    });

    console.log('Response status:', response.status);

    if (!response.ok) {
      const text = await response.text();
      onError(`Request failed: ${response.status} - ${text}`);
      onDone();
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      onError('Response body is not readable');
      onDone();
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      console.log('Received chunk, buffer length:', buffer.length);

      // Try to extract complete JSON objects from buffer
      const jsonObjects = extractJsonObjects(buffer);

      for (const obj of jsonObjects.objects) {
        console.log('Parsed object:', obj);
        if (obj.response) {
          onText(obj.response);
        }
        if (obj.error) {
          onError(obj.error);
        }
      }

      buffer = jsonObjects.remaining;
    }

    // Handle any remaining buffer content
    if (buffer.trim()) {
      try {
        const data = JSON.parse(buffer);
        if (data.response) {
          onText(data.response);
        }
        if (data.error) {
          onError(data.error);
        }
      } catch {
        console.warn('Unparsed remaining buffer:', buffer);
      }
    }

    onDone();
  } catch (err) {
    console.error('Streaming error:', err);
    onError(err instanceof Error ? err.message : 'Unknown error');
    onDone();
  }
}

// Extract complete JSON objects from a buffer string
function extractJsonObjects(buffer: string): { objects: ApiResponse[]; remaining: string } {
  const objects: ApiResponse[] = [];
  let remaining = buffer;

  let braceCount = 0;
  let startIndex = -1;
  let inString = false;
  let escapeNext = false;

  for (let i = 0; i < remaining.length; i++) {
    const char = remaining[i];

    if (escapeNext) {
      escapeNext = false;
      continue;
    }

    if (char === '\\' && inString) {
      escapeNext = true;
      continue;
    }

    if (char === '"') {
      inString = !inString;
      continue;
    }

    if (inString) continue;

    if (char === '{') {
      if (braceCount === 0) startIndex = i;
      braceCount++;
    } else if (char === '}') {
      braceCount--;
      if (braceCount === 0 && startIndex !== -1) {
        const jsonStr = remaining.substring(startIndex, i + 1);
        try {
          const obj = JSON.parse(jsonStr);
          objects.push(obj);
          remaining = remaining.substring(i + 1);
          // Reset for next object
          i = -1;
          startIndex = -1;
        } catch {
          // Incomplete JSON, keep in buffer
        }
      }
    }
  }

  return { objects, remaining };
}
