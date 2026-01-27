import { useState, useCallback, useRef } from 'react';
import { useAuth } from './context/AuthContext';
import { sendPromptStreaming } from './api/runtime';
import { signInWithRedirect } from 'aws-amplify/auth';
import './App.css';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

function App() {
  const { isAuthenticated, isLoading: authLoading, getIdToken, signOut, user } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const contentRef = useRef('');

  const handleSend = useCallback(async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    };

    const assistantId = `assistant-${Date.now()}`;
    contentRef.current = '';

    setMessages(prev => [...prev, userMessage, {
      id: assistantId,
      role: 'assistant',
      content: '',
    }]);
    setInput('');
    setIsLoading(true);

    try {
      const token = await getIdToken();
      if (!token) {
        setMessages(prev => prev.map(msg =>
          msg.id === assistantId
            ? { ...msg, content: 'Error: Not authenticated. Please sign in again.' }
            : msg
        ));
        setIsLoading(false);
        return;
      }

      await sendPromptStreaming(
        userMessage.content,
        token,
        // onText - called when text content arrives
        (text) => {
          contentRef.current = text;
          setMessages(prev => prev.map(msg =>
            msg.id === assistantId
              ? { ...msg, content: text }
              : msg
          ));
        },
        // onError - called on error
        (error) => {
          setMessages(prev => prev.map(msg =>
            msg.id === assistantId
              ? { ...msg, content: `Error: ${error}` }
              : msg
          ));
        },
        // onDone - called when streaming completes
        () => {
          if (!contentRef.current) {
            setMessages(prev => prev.map(msg =>
              msg.id === assistantId
                ? { ...msg, content: 'No response received.' }
                : msg
            ));
          }
          setIsLoading(false);
        }
      );
    } catch (err) {
      console.error('Error:', err);
      setMessages(prev => prev.map(msg =>
        msg.id === assistantId
          ? { ...msg, content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}` }
          : msg
      ));
      setIsLoading(false);
    }
  }, [input, isLoading, getIdToken]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (authLoading) {
    return (
      <div className="loading">
        <p>Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="login-container">
        <h1>Central Ops Agent</h1>
        <p>Multi-account AWS operations assistant</p>
        <button onClick={() => signInWithRedirect()} className="login-btn">
          Sign In with Cognito
        </button>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Central Ops Agent</h1>
        <div className="user-info">
          <span>{user?.signInDetails?.loginId || 'User'}</span>
          <button onClick={signOut} className="signout-btn">Sign Out</button>
        </div>
      </header>

      <main className="chat-container">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty-state">
              <p>Ask me about your AWS resources across accounts.</p>
              <p className="hint">Try: "List S3 buckets in the Central account"</p>
            </div>
          )}
          {messages.map(msg => (
            <div key={msg.id} className={`message ${msg.role}`}>
              <div className="message-content">
                <pre>{msg.content || (isLoading && msg.role === 'assistant' ? 'Thinking...' : '')}</pre>
              </div>
            </div>
          ))}
        </div>

        <div className="input-container">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask about AWS resources..."
            disabled={isLoading}
            rows={2}
          />
          <button onClick={handleSend} disabled={isLoading || !input.trim()}>
            {isLoading ? 'Sending...' : 'Send'}
          </button>
        </div>
      </main>
    </div>
  );
}

export default App;
