import { useState, useCallback, useRef } from 'react';
import { Header } from './components/Header';
import { ChatContainer } from './components/ChatContainer';
import { useAuth } from './hooks/useAuth';
import { sendPromptStreaming, type StreamChunk } from './api/runtime';
import type { ChatMessage } from './types/runtime';

function App() {
  const { isAuthenticated, isLoading: authLoading, getIdToken } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const assistantMessageRef = useRef<string>('');

  const handleSendMessage = useCallback(async (content: string) => {
    // Add user message
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    assistantMessageRef.current = '';

    // Create assistant message placeholder
    const assistantId = crypto.randomUUID();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, assistantMessage]);

    try {
      const token = await getIdToken();
      if (!token) {
        throw new Error('Not authenticated');
      }

      await sendPromptStreaming(content, token, (chunk: StreamChunk) => {
        switch (chunk.type) {
          case 'text':
            if (chunk.content) {
              assistantMessageRef.current += chunk.content;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantId
                    ? { ...msg, content: assistantMessageRef.current }
                    : msg
                )
              );
            }
            break;

          case 'tool_call':
            // Show tool call in progress
            const toolCallText = `\n\n*Calling ${chunk.name}...*\n`;
            assistantMessageRef.current += toolCallText;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, content: assistantMessageRef.current }
                  : msg
              )
            );
            break;

          case 'tool_result':
            // Tool result received, model will continue
            break;

          case 'error':
            assistantMessageRef.current += `\n\nError: ${chunk.content}`;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, content: assistantMessageRef.current }
                  : msg
              )
            );
            break;

          case 'done':
            // Streaming complete
            break;
        }
      });

      // If no content was streamed, show a default message
      if (!assistantMessageRef.current) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, content: 'No response received.' }
              : msg
          )
        );
      }
    } catch (err) {
      // Update assistant message with error
      const errorContent = `Error: ${err instanceof Error ? err.message : 'Unknown error'}`;
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? { ...msg, content: errorContent }
            : msg
        )
      );
    } finally {
      setIsLoading(false);
    }
  }, [getIdToken]);

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg text-gray-600">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="max-w-4xl mx-auto">
        {isAuthenticated ? (
          <ChatContainer
            messages={messages}
            onSendMessage={handleSendMessage}
            isLoading={isLoading}
          />
        ) : (
          <div className="px-4 py-8">
            <div className="bg-white shadow rounded-lg p-6 text-center">
              <h2 className="text-lg font-medium text-gray-900 mb-4">
                Welcome to Central Ops Agent
              </h2>
              <p className="text-gray-600 mb-4">
                Sign in to chat with the agent and query AWS resources across your accounts.
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
