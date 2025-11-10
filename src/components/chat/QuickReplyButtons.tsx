import { Button } from "@/components/ui/button";
import { MapPin, Users, TrendingUp } from "lucide-react";

interface QuickReplyButtonsProps {
  onSelect: (action: string) => void;
}

const QuickReplyButtons = ({ onSelect }: QuickReplyButtonsProps) => {
  const buttons = [
    { icon: MapPin, label: "Campus Map", action: "map" },
    { icon: Users, label: "Find Faculty", action: "faculty" },
    { icon: TrendingUp, label: "Placements", action: "placements" },
  ];

  return (
    <div className="flex w-full justify-start animate-fade-in-up">
      <div className="flex flex-wrap gap-2">
        {buttons.map((button) => (
          <Button
            key={button.action}
            variant="outline"
            size="sm"
            onClick={() => onSelect(button.action)}
            className="rounded-full bg-secondary hover:bg-primary hover:text-primary-foreground transition-all duration-300"
          >
            <button.icon className="mr-2 h-4 w-4" />
            {button.label}
          </Button>
        ))}
      </div>
    </div>
  );
};

export default QuickReplyButtons;
