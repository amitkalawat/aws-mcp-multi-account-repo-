import { useRef, useEffect } from 'react';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import type { ChatMessage as ChatMessageType } from '../types/runtime';

interface ChatContainerProps {
  messages: ChatMessageType[];
  onSendMessage: (message: string) => void;
  isLoading: boolean;
}

export function ChatContainer({ messages, onSendMessage, isLoading }: ChatContainerProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex flex-col h-[calc(100vh-180px)]">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 mt-8">
            <p className="text-lg mb-4">Welcome to Central Ops Agent</p>
            <p className="text-sm">Ask questions about your AWS resources across accounts.</p>
            <div className="mt-6 text-left max-w-md mx-auto bg-gray-50 rounded-lg p-4">
              <p className="text-xs font-medium text-gray-700 mb-2">Example queries:</p>
              <ul className="text-xs text-gray-600 space-y-1">
                <li>"List all S3 buckets in the production account"</li>
                <li>"How many EC2 instances are running in staging?"</li>
                <li>"Show me Lambda functions in account 123456789012"</li>
                <li>"What RDS databases exist across all accounts?"</li>
              </ul>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="border-t bg-white p-4">
        <ChatInput onSend={onSendMessage} isLoading={isLoading} />
      </div>
    </div>
  );
}
