import { RUNTIME_URL } from '../config/amplify';
import type { RuntimeRequest, RuntimeResponse } from '../types/runtime';

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
