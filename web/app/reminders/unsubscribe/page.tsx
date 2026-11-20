import type { Metadata } from "next";

import { Unsubscribe } from "./Unsubscribe";

export const metadata: Metadata = {
  title: "退订截止提醒 · 鱼跃彼岸",
  robots: { index: false, follow: false },
  // The address carries the unsubscribe token; it is not sent on to any page linked from here.
  referrer: "no-referrer",
};

/** Where the unsubscribe link in a reminder email lands. Public: the token and one press of the button are the whole request. */
export default function UnsubscribePage() {
  return <Unsubscribe />;
}
