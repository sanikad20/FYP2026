import { Card } from "@/components/ui/card";

const PlacementChart = () => {
  return (
    <div className="flex w-full justify-start animate-fade-in-up">
      <Card className="max-w-[90%] p-6 bg-card shadow-card">
        <h3 className="text-sm font-semibold mb-4 text-foreground">
          Placement Statistics
        </h3>
        <p className="text-sm text-muted-foreground">
          No verified placement statistics are available in the assistant yet.
        </p>
        <a
          href="https://vjti.ac.in/training-and-placement-office/"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-block text-sm font-medium text-primary underline underline-offset-4"
        >
          Visit VJTI Training and Placement Office
        </a>
      </Card>
    </div>
  );
};

export default PlacementChart;
