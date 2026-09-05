import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"

import type { PipelineStatus } from "@/lib/api"

export function useLiveEvents(onStatus: (status: PipelineStatus) => void) {
  const queryClient = useQueryClient()

  useEffect(() => {
    const eventSource = new EventSource("/api/events")
    const onOccurrence = (event: MessageEvent<string>) => {
      JSON.parse(event.data)
      void queryClient.invalidateQueries({ queryKey: ["occurrences"] })
      void queryClient.invalidateQueries({ queryKey: ["stats"] })
    }
    const handleStatus = (event: MessageEvent<string>) => {
      onStatus(JSON.parse(event.data) as PipelineStatus)
    }
    eventSource.addEventListener("occurrence", onOccurrence as EventListener)
    eventSource.addEventListener("status", handleStatus as EventListener)
    return () => eventSource.close()
  }, [onStatus, queryClient])
}
