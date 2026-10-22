import { Alert, Button, Code, Stack } from "@mantine/core";
import { Component, type ReactNode } from "react";

/** Keeps a crash in one page from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Alert color="red" title="Something went wrong on this page">
        <Stack gap="xs">
          <Code>{this.state.error.message}</Code>
          <Button size="xs" variant="default" w="fit-content" onClick={() => this.setState({ error: null })}>Try again</Button>
        </Stack>
      </Alert>
    );
  }
}
