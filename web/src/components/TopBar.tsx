import { Link } from "react-router-dom";
import { Activity, Clapperboard, RadioTower } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/fields";

export function TopBar({ variant = "ghost" }: { variant?: "ghost" | "default" }) {
  return (
    <header
      className={cn(
        "sticky top-0 z-20 border-b border-edge/70 bg-ink/80 backdrop-blur-md",
        variant === "default" && "relative"
      )}
    >
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-3">
        <Link to="/" className="flex items-center gap-2 font-extrabold tracking-tight">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-neon opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-neon shadow-[0_0_12px_#38e1ff]" />
          </span>
          OpenAIudio
        </Link>
        <nav className="ml-auto flex items-center gap-1 text-sm font-medium text-mute">
          <Link to="/" className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-white">
            <Activity className="size-4 text-neon" /> Audiencia
          </Link>
          <Link to="/broadcast" className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-white">
            <RadioTower className="size-4 text-neon" /> Broadcast
          </Link>
          <Link to="/admin" className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-white">
            <Clapperboard className="size-4 text-neon" /> Producción
          </Link>
        </nav>
        <Badge className="hidden sm:inline-flex text-emerald-300 border-emerald-400/30 bg-emerald-400/5">
          live captions
        </Badge>
      </div>
    </header>
  );
}