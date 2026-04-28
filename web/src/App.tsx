import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "#root/constant.ts";
import NewChatPanel from "#root/layout/NewChatPanel.tsx";

function App() {
	return (
		<QueryClientProvider client={queryClient}>
			<NewChatPanel />
		</QueryClientProvider>
	);
}

export default App;
