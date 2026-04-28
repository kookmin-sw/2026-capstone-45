import { Header } from "#root/component/Header";
import { LeftAside } from "./LeftAside";
import { MainWorkspace } from "./MainWorkspace";

export const MainLayout = () => {
	return (
		<div className="flex h-screen w-screen overflow-hidden bg-background text-foreground font-sans">
			<LeftAside />
			<div className="flex-1 flex flex-col min-w-0">
				<Header />
				<MainWorkspace />
			</div>
		</div>
	);
};
