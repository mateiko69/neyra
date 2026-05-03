import type { ReactNode } from "react";
import { EmptyState } from "../EmptyState";

type ChatEmptyStateProps = {
  kicker?: string;
  title: string;
  description: string;
  children?: ReactNode;
  allowRawDescription?: boolean;
};

export function ChatEmptyState({ kicker, title, description, children, allowRawDescription }: ChatEmptyStateProps) {
  return (
    <div className="chat-empty-wrap">
      <EmptyState kicker={kicker} title={title} description={description} spacious allowRawDescription={allowRawDescription}>
        {children}
      </EmptyState>
    </div>
  );
}
