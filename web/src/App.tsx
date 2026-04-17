import { QueryClientProvider } from "@tanstack/react-query";
import DocumentRender from "./components/DocumentRender";
import { queryClient } from "./constant";

function App() {
	return (
		<QueryClientProvider client={queryClient}>
			<DocumentRender />
		</QueryClientProvider>
	);
}

export default App;
