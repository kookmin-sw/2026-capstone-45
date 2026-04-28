import { notifications } from "@mantine/notifications";
import { QueryClient } from "@tanstack/react-query";
import axios from "axios";

export const queryClient = new QueryClient();

export const axiosInstance = axios.create({
	baseURL: "/api",
});

axiosInstance.interceptors.response.use(
	(response) => response,
	(error) => {
		notifications.show({
			title: "오류",
			message: "네트워크/서버 오류가 발생했습니다",
			color: "red",
		});
		return Promise.reject(error);
	},
);
