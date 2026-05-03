"use client";

import { Suspense } from "react";
import { SubscriptionPageFallback, SubscriptionPlansContent } from "./SubscriptionPlansScreen";

export default function SubscriptionPage() {
  return (
    <Suspense fallback={<SubscriptionPageFallback />}>
      <SubscriptionPlansContent />
    </Suspense>
  );
}
