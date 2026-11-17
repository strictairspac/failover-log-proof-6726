/** @typedef {{id:number,name:string,role:'leader'|'follower',term:number,log_position:number,available:boolean,fenced:boolean,vote_enabled:boolean}} Node */
/** @typedef {{id:number,name:string,fail_primary:boolean,fence_primary:boolean,max_data_loss:number,required_term:number}} Scenario */
/** @typedef {{id:number,scenario_id:number,label:string,status:string,snapshot:object,result:object|null}} Drill */
/** @typedef {{id:number,batch_key:string,node_name:string,committed_position:number,committed_digest:string,segment_count:number,version:number,created_at:string}} ProofBatch */
/** @typedef {{node:string,proven_tip:number,tip_digest:string,first_gap:number|null,break_position:number|null,staged:number,fork_position:number|null,committed_position:number|null,committed_digest:string|null}} ProofChainStatus */
export {};
