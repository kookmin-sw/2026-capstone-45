import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "#root/constant.ts";
import { MainLayout } from "#root/layout/MainLayout.tsx";

export const App = () => {
	return (
		<QueryClientProvider client={queryClient}>
			<MainLayout />
		</QueryClientProvider>
	);
};
