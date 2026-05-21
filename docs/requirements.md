# Requirements

## Goal

Build a small AI agency pipeline that can take a client request, clarify the objective, generate deliverables, review the result, and save the final output.

The first version should focus on a simple but complete workflow rather than a complex multi-agent system.

## Target Workflow

1. Receive a client request.
2. Extract the goal, audience, constraints, and expected output.
3. Create a short execution plan.
4. Generate the requested deliverable.
5. Review the deliverable for quality, missing details, and format issues.
6. Save the final result.

## Example Use Cases

- Marketing copy generation
- Blog post drafting
- Landing page content
- Social media content planning
- Client proposal drafts
- Research summaries
- Email campaign drafts

## Inputs

- Client request text
- Desired output type
- Brand or tone guidelines
- Target audience
- Optional reference material

## Outputs

- Structured brief
- Execution plan
- Draft deliverable
- Review notes
- Final deliverable

## Functional Requirements

- The system must accept a text request from a user.
- The system must convert the request into a structured brief.
- The system must generate a task plan from the brief.
- The system must produce a draft output.
- The system must run a review step before finalizing.
- The system must save generated outputs in a predictable directory.

## Non-Functional Requirements

- Keep the first version simple and runnable locally.
- Make each pipeline step easy to inspect and debug.
- Store intermediate files so failures can be reviewed.
- Avoid hard-coding one specific business niche.
- Design the project so more agents or steps can be added later.

## Out of Scope for V1

- User authentication
- Payment integration
- Production deployment
- Complex UI
- CRM integration
- Fully autonomous client communication
