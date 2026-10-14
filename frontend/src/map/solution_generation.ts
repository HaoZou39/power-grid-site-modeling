/** Invalidates asynchronous results that belong to an older displayed-solution set. */
export class SolutionGeneration {
  private value = 0;

  capture(): number {
    return this.value;
  }

  advance(): number {
    this.value += 1;
    return this.value;
  }

  isCurrent(value: number): boolean {
    return value === this.value;
  }
}
