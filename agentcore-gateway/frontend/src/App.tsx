import { useState, useCallback } from 'react';
import { Header } from './components/Header';
import { ChatContainer } from './components/ChatContainer';
import { useAuth } from './hooks/useAuth';
import { sendPrompt } from './api/runtime';
import type { ChatMessage } from './types/runtime';

function App() {
  const { isAuthenticated, isLoading: authLoading, getIdToken } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

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

    try {
      const token = await getIdToken();
      if (!token) {
        throw new Error('Not authenticated');
      }

      const response = await sendPrompt(content, token);

      // Add assistant message
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      // Add error as assistant message
      const errorMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
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
