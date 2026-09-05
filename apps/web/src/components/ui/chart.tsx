import * as React from "react"
import * as RechartsPrimitive from "recharts"

import { cn } from "@/lib/utils"

export type ChartConfig = Record<string, { label?: React.ReactNode; color?: string }>

const ChartContext = React.createContext<{ config: ChartConfig } | null>(null)

function ChartContainer({
  config,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  config: ChartConfig
  children: React.ComponentProps<typeof RechartsPrimitive.ResponsiveContainer>["children"]
}) {
  const style = Object.entries(config).reduce(
    (acc, [key, item]) => {
      if (item.color) acc[`--color-${key}`] = item.color
      return acc
    },
    {} as Record<string, string>,
  )

  return (
    <ChartContext.Provider value={{ config }}>
      <div className={cn("flex aspect-video justify-center text-xs", className)} style={style} {...props}>
        <RechartsPrimitive.ResponsiveContainer>{children}</RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  )
}

function ChartTooltipContent({
  active,
  payload,
  label,
}: Partial<RechartsPrimitive.TooltipContentProps<number, string>>) {
  const context = React.useContext(ChartContext)
  if (!active || !payload?.length) return null
  return (
    <div className="min-w-32 rounded-xl border border-white/10 bg-[#11161d]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur">
      <p className="mb-1 text-muted-foreground">{label}</p>
      {payload.map((item) => (
        <div key={String(item.dataKey)} className="flex items-center justify-between gap-6 font-medium">
          <span>{context?.config[String(item.dataKey)]?.label ?? item.name}</span>
          <span className="font-mono">{item.value}</span>
        </div>
      ))}
    </div>
  )
}

const ChartTooltip = RechartsPrimitive.Tooltip

export { ChartContainer, ChartTooltip, ChartTooltipContent }
