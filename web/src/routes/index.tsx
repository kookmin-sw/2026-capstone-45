import { createFileRoute } from "@tanstack/react-router";
import { MainLayout } from "#root/layout/MainLayout";

export const Route = createFileRoute("/")({
	component: MainLayout,
});
