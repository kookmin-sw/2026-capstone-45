import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "#root/constant.ts";
import { MainLayout } from "#root/layout/MainLayout.tsx";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";

export const App = () => {
	return (
		<MantineProvider>
			<Notifications />
			<QueryClientProvider client={queryClient}>
				<MainLayout />
			</QueryClientProvider>
		</MantineProvider>
	);
};
