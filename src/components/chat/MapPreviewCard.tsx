import { Button } from "@/components/ui/button";
import { MapPin, ExternalLink } from "lucide-react";

const MapPreviewCard = () => {
  return (
    <div className="flex w-full justify-start animate-fade-in-up">
      <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-card border border-border shadow-card overflow-hidden">
        <div className="relative h-48 bg-gradient-to-br from-primary-light to-secondary">
          <div className="absolute inset-0 flex items-center justify-center">
            <MapPin className="h-16 w-16 text-primary animate-pulse" />
          </div>
          <div className="absolute bottom-2 left-2 right-2 bg-background/90 backdrop-blur-sm rounded-lg p-2">
            <p className="text-xs font-medium">Library - Main Campus</p>
            <p className="text-xs text-muted-foreground">Building A, Ground Floor</p>
          </div>
        </div>
        <div className="p-4">
          <Button
            className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
            size="sm"
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Get Directions
          </Button>
        </div>
      </div>
    </div>
  );
};

export default MapPreviewCard;
