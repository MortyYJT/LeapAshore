// One read of one server resource, as every page sees it: `{ data, error, loading, reload }` (design D1).
// The state transitions are a pure function so the error path can be tested without React.

export interface LoadState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export interface Resource<T> extends LoadState<T> {
  reload: () => void;
}

export const INITIAL: LoadState<never> = { data: null, error: null, loading: true };

/**
 * Run a read and return the state it leaves. A failed reload keeps the data already on screen: the
 * applicant keeps what they were reading, and the error says the refresh did not land.
 */
export async function settle<T>(load: () => Promise<T>, previous: LoadState<T>): Promise<LoadState<T>> {
  try {
    return { data: await load(), error: null, loading: false };
  } catch (error: unknown) {
    return {
      data: previous.data,
      error: error instanceof Error && error.message ? error.message : "读取失败，请稍后再试。",
      loading: false,
    };
  }
}
