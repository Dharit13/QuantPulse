"use client";

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  type ColumnDef,
  flexRender,
} from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { motion } from "framer-motion";
import { Badge } from "./badge";
import { GlowingEffect } from "./ui/glowing-effect";
import type { SectorRecommendation } from "@/lib/types";
import type { BadgeVariant } from "@/lib/types";

function ReturnCell({ value }: { value: number }) {
  const color = value >= 0 ? "text-emerald-400" : "text-rose-400";
  return (
    <span className={`text-[13px] font-medium ${color}`}>
      {value >= 0 ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}

function SortIcon({ sorted }: { sorted: false | "asc" | "desc" }) {
  if (sorted === "asc") return <ChevronUp className="h-3.5 w-3.5" />;
  if (sorted === "desc") return <ChevronDown className="h-3.5 w-3.5" />;
  return <ChevronsUpDown className="h-3.5 w-3.5 text-foreground/80/50" />;
}

const columns: ColumnDef<SectorRecommendation>[] = [
  {
    accessorKey: "sector",
    header: "Sector",
    cell: (info) => (
      <span className="text-[14px] font-semibold text-foreground">
        {info.getValue() as string}
      </span>
    ),
    enableSorting: true,
  },
  {
    accessorKey: "etf",
    header: "ETF",
    cell: (info) => (
      <span className="text-[12px] text-foreground/80">
        {info.getValue() as string}
      </span>
    ),
    enableSorting: false,
  },
  {
    accessorKey: "return_5d",
    header: "5D Return",
    cell: (info) => <ReturnCell value={info.getValue() as number} />,
    enableSorting: true,
  },
  {
    accessorKey: "return_20d",
    header: "20D Return",
    cell: (info) => <ReturnCell value={info.getValue() as number} />,
    enableSorting: true,
  },
  {
    accessorKey: "rsi",
    header: "RSI",
    cell: (info) => (
      <span className="text-[12px] text-foreground">
        {(info.getValue() as number).toFixed(0)}
      </span>
    ),
    enableSorting: true,
  },
  {
    accessorKey: "score",
    header: "Score",
    cell: (info) => {
      const score = info.getValue() as number;
      const variant: BadgeVariant =
        score >= 70 ? "green" : score >= 50 ? "amber" : "red";
      return <Badge variant={variant}>{score}</Badge>;
    },
    enableSorting: true,
  },
  {
    accessorKey: "verdict",
    header: "Verdict",
    cell: (info) => {
      const v = info.getValue() as string;
      const variant: BadgeVariant =
        v === "BUY" ? "green" : v === "HOLD" ? "amber" : "red";
      return <Badge variant={variant}>{v}</Badge>;
    },
    enableSorting: true,
  },
];

interface SectorTableProps {
  sectors: SectorRecommendation[];
}

export function SectorTable({ sectors }: SectorTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "score", desc: true },
  ]);

  const data = useMemo(() => sectors, [sectors]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="relative rounded-[1.25rem] border-[0.75px] border-border p-2 md:rounded-[1.5rem] md:p-3">
      <GlowingEffect
        spread={40}
        glow
        disabled={false}
        proximity={64}
        inactiveZone={0.01}
        borderWidth={3}
      />
      <div className="relative rounded-xl border-[0.75px] border-border bg-background overflow-hidden shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="border-b border-border">
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className="px-4 py-3 text-left text-[11px] uppercase tracking-wider text-foreground font-semibold"
                    >
                      {header.column.getCanSort() ? (
                        <button
                          className="flex items-center gap-1 cursor-pointer hover:text-foreground transition-colors"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                          <SortIcon
                            sorted={header.column.getIsSorted()}
                          />
                        </button>
                      ) : (
                        flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row, i) => (
                <motion.tr
                  key={row.id}
                  className="border-b border-border/50 last:border-b-0 hover:bg-muted/30 transition-colors"
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: i * 0.03 }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
