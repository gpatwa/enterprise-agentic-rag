// Simplified shadcn use-toast hook (single global queue, no genId/dedupe rules
// from the full reference). Sufficient for our W1 needs.
import * as React from 'react';
import type {
  ToastActionElement,
  ToastProps,
} from './toast';

const TOAST_LIMIT = 3;
const TOAST_REMOVE_DELAY = 5_000;

type ToasterToast = ToastProps & {
  id: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: ToastActionElement;
};

let count = 0;
function genId() {
  count = (count + 1) % Number.MAX_SAFE_INTEGER;
  return count.toString();
}

interface State {
  toasts: ToasterToast[];
}

type Action =
  | { type: 'ADD'; toast: ToasterToast }
  | { type: 'DISMISS'; toastId?: string }
  | { type: 'REMOVE'; toastId?: string };

const listeners: Array<(state: State) => void> = [];
let memoryState: State = { toasts: [] };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'ADD':
      return { ...state, toasts: [action.toast, ...state.toasts].slice(0, TOAST_LIMIT) };
    case 'DISMISS':
      return {
        ...state,
        toasts: state.toasts.map((t) =>
          action.toastId === undefined || t.id === action.toastId ? { ...t, open: false } : t
        ),
      };
    case 'REMOVE':
      return {
        ...state,
        toasts: action.toastId
          ? state.toasts.filter((t) => t.id !== action.toastId)
          : [],
      };
  }
}

function dispatch(action: Action) {
  memoryState = reducer(memoryState, action);
  listeners.forEach((l) => l(memoryState));
}

export function toast(opts: Omit<ToasterToast, 'id'>) {
  const id = genId();
  dispatch({
    type: 'ADD',
    toast: {
      ...opts,
      id,
      open: true,
      onOpenChange: (open) => {
        if (!open) dispatch({ type: 'DISMISS', toastId: id });
      },
    },
  });
  setTimeout(() => dispatch({ type: 'REMOVE', toastId: id }), TOAST_REMOVE_DELAY);
  return { id };
}

export function useToast() {
  const [state, setState] = React.useState<State>(memoryState);
  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const i = listeners.indexOf(setState);
      if (i > -1) listeners.splice(i, 1);
    };
  }, []);
  return { ...state, toast };
}
