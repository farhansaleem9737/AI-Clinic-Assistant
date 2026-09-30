import { describe, expect, it } from "vitest";
import { directoryApiParams, directorySearchParams, EMPTY_FILTERS, pageWindow, readDirectoryState } from "./doctors";

const read = (query) => readDirectoryState(new URLSearchParams(query));

describe("directory state in the URL", () => {
  it("has sensible defaults for an empty URL", () => {
    expect(read("")).toEqual({ filters: EMPTY_FILTERS, sort: "name_asc", page: 1, view: "grid" });
  });

  it("reads search, filters, sort, page and view", () => {
    expect(read("q=cardio&department=dep-1&specialization=Cardiologist&min_experience=10&fee=150-200&sort=fee_desc&page=3&view=list")).toEqual({
      filters: { q: "cardio", department: "dep-1", specialization: "Cardiologist", min_experience: "10", fee: "150-200" },
      sort: "fee_desc",
      page: 3,
      view: "list",
    });
  });

  it("ignores values it does not recognise", () => {
    const state = read("sort=drop_table&page=-4&view=carousel&fee=free&min_experience=abc");
    expect(state).toEqual({ filters: EMPTY_FILTERS, sort: "name_asc", page: 1, view: "grid" });
  });

  it("writes only what differs from the defaults", () => {
    expect(directorySearchParams(read(""))).toEqual({});
    expect(directorySearchParams({ filters: { ...EMPTY_FILTERS, q: "  lee " }, sort: "fee_asc", page: 2, view: "list" })).toEqual({
      q: "lee",
      sort: "fee_asc",
      page: "2",
      view: "list",
    });
  });

  it("round-trips through the URL", () => {
    const query = "q=cardio&department=dep-1&fee=200-plus&sort=experience_desc&page=2";
    expect(new URLSearchParams(directorySearchParams(read(query))).toString()).toBe(query);
  });
});

describe("API parameters", () => {
  const params = (filters, rest = {}) => directoryApiParams({ filters: { ...EMPTY_FILTERS, ...filters }, sort: "name_asc", page: 1, ...rest });

  it("always sends page, page size and sort", () => {
    expect(params({})).toEqual({ page: 1, page_size: 6, sort: "name_asc" });
  });

  it("maps filters to the API names", () => {
    expect(params({ q: " lee ", department: "dep-1", specialization: "Cardiologist", min_experience: "5" }, { page: 2 })).toEqual({
      page: 2,
      page_size: 6,
      sort: "name_asc",
      q: "lee",
      department_id: "dep-1",
      specialization: "Cardiologist",
      min_experience: "5",
    });
  });

  it.each([
    ["under-100", { fee_max: "99.99" }],
    ["100-150", { fee_min: "100", fee_max: "149.99" }],
    ["150-200", { fee_min: "150", fee_max: "199.99" }],
    ["200-plus", { fee_min: "200" }],
  ])("turns the fee range %s into bounds", (fee, bounds) => {
    expect(params({ fee })).toEqual({ page: 1, page_size: 6, sort: "name_asc", ...bounds });
  });
});

describe("pageWindow", () => {
  it.each([
    [1, 1, [1]],
    [1, 2, [1, 2]],
    [1, 8, [1, 2, 3, 4, null, 8]],
    [5, 12, [1, null, 4, 5, 6, null, 12]],
    [8, 8, [1, null, 5, 6, 7, 8]],
    [3, 5, [1, 2, 3, 4, 5]],
  ])("page %i of %i", (current, total, expected) => {
    expect(pageWindow(current, total)).toEqual(expected);
  });
});
